#include "protocol.h"

#include <string.h>

int mk_request_build(uint8_t out[MCHOSE_REPORT_LEN])
{
    if (!out)
        return -1;

    uint8_t body[19] = {
        [0]  = MCHOSE_REPORT_ID,
        [1]  = MCHOSE_COMMAND_ID,
        [2]  = 0x01,
        /* 3..18 are zero */
    };
    unsigned int sum = 0;
    for (int i = 0; i < 19; i++)
        sum += body[i];

    memcpy(out, body, 19);
    out[19] = (uint8_t)(sum & 0xFF);
    return MCHOSE_REPORT_LEN;
}

int mk_response_parse(const uint8_t *report, size_t len,
                      int *pct, uint8_t *status, int *checksum_ok)
{
    if (!report || len != MCHOSE_REPORT_LEN)
        return -1;
    if (report[0] != MCHOSE_REPORT_ID)
        return -1;
    if (report[1] != MCHOSE_COMMAND_ID)
        return -1;
    int percentage = report[5];
    if (percentage < 0 || percentage > 100)
        return -1;

    if (pct)
        *pct = percentage;
    if (status)
        *status = report[6];
    if (checksum_ok) {
        unsigned int s = 0;
        for (size_t i = 0; i < MCHOSE_REPORT_LEN - 1; i++)
            s += report[i];
        *checksum_ok = ((s & 0xFF) == report[MCHOSE_REPORT_LEN - 1]) ? 1 : 0;
    }
    return 0;
}

int mk_charge_state(uint8_t status)
{
    /* Observed on the K99 with M HUB cross-checked:
     *   0x10 when USB cable plugged in (charging)
     *   0x01 when full and unplugged
     *   0x00 when discharging normally
     */
    if (status & 0x10)
        return 1;  /* charging */
    if (status & 0x01)
        return 2;  /* full */
    return 0;      /* discharging */
}

int mk_k99v3_request_build(uint8_t *out, size_t out_len)
{
    if (!out || out_len < MCHOSE_K99_V3_REPORT_LEN)
        return -1;
    /* Confirmed wire shape:
     *   55 03 00 38 38 00 00 00   -- magic, cmd 0x03, sub-cmd 0x38
     *                                 (sub-cmd is the 4-byte LE 0x3800
     *                                 little-endian; bytes 2-3 echo
     *                                 back as 00 38 in the response)
     *   56 zero bytes              -- rest of the 64-byte report
     *
     * No documented checksum. The response's sub-cmd echo (00 38)
     * is used by mk_k99v3_response_parse() as the framing check. */
    static const uint8_t prefix[8] = {
        0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00,
    };
    memcpy(out, prefix, sizeof(prefix));
    memset(out + sizeof(prefix), 0,
           MCHOSE_K99_V3_REPORT_LEN - sizeof(prefix));
    return MCHOSE_K99_V3_REPORT_LEN;
}

int mk_k99v3_response_parse(const uint8_t *buf, size_t len,
                           int *pct, uint8_t *status,
                           int *checksum_ok)
{
    if (!buf || len != MCHOSE_K99_V3_REPORT_LEN)
        return -1;
    if (buf[0] != 0xAA)                    /* magic */
        return -1;
    if (buf[1] != 0x03)                    /* cmd echo */
        return -1;
    if (buf[2] != 0x00 || buf[3] != 0x38)  /* sub-cmd echo */
        return -1;
    int percentage = buf[8];
    if (percentage < 0 || percentage > 100)
        return -1;

    if (pct)
        *pct = percentage;
    if (status)
        /* Byte 6 is captured for diagnostic logging only. Its charge
         * semantics on V3 are NOT documented; do not interpret it as
         * "charging" or "full" anywhere in the pipeline. The V3
         * profile's charge_state() function ignores this byte and
         * always returns 0 (discharging) to keep UPower honest. */
        *status = buf[6];
    if (checksum_ok)
        /* V3 has no checksum. Treat the framing check above as the
         * sole integrity gate; always report OK so the existing
         * pipeline (which prints "checksum=ok" in --raw mode) keeps
         * working. */
        *checksum_ok = 1;
    return 0;
}
