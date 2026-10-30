/* MCHOSE K99 wire-protocol helpers.
 *
 * Pure functions: no I/O, no globals. Safe to unit-test.
 *
 * Two generations live here:
 *   - Legacy K99 (Compx 2.4G receiver, vendor 0x05AC / product 0x024F):
 *     20-byte reports with a leading report id, vendor command 0x4A,
 *     and a trailing byte-sum checksum. The functions mk_request_build /
 *     mk_response_parse / mk_charge_state below implement this wire
 *     shape; this is the historical K99 path and is preserved as-is.
 *   - K99 V3 (MCHOSE 0x3837 / 0x3033): the battery channel is the
 *     boot-mouse HID interface with 64-byte raw interrupt I/O and no
 *     report-id prefix. See the V3 section below.
 */

#ifndef MCHOSE_K99_PROTOCOL_H
#define MCHOSE_K99_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#define MCHOSE_REPORT_ID   0x13
#define MCHOSE_COMMAND_ID  0x4A
#define MCHOSE_REPORT_LEN  20

/* Build the 20-byte battery read request into `out`.
 * Returns the number of bytes written (always 20) or -1 if `out` is NULL. */
int mk_request_build(uint8_t out[MCHOSE_REPORT_LEN]);

/* Parse a 20-byte response. On success returns 0 and writes the
 * percentage (0-100) into *pct, the status byte into *status, and
 * sets *checksum_ok to 1 if the trailing byte matches the byte sum,
 * 0 otherwise. Returns -1 on invalid length, report id, command, or
 * percentage range. */
int mk_response_parse(const uint8_t *report, size_t len,
                      int *pct, uint8_t *status, int *checksum_ok);

/* Map the K99 status byte (high nibble = full, low nibble = charge)
 * to a stable charge-state code:
 *   0 = discharging / idle
 *   1 = charging
 *   2 = fully charged (not charging)
 */
int mk_charge_state(uint8_t status);

/* K99 V3 protocol (MCHOSE vendor 0x3837 / product 0x3033, boot-mouse
 * interface). Raw 64-byte interrupt I/O; no report id prefix.
 *
 * Confirmed wire shape:
 *   request  (64 bytes): 55 03 00 38 38 00 00 00 <56 zero bytes>
 *   response (64 bytes): AA 03 00 38 ... <percent at byte 8> ...
 *
 * Bytes 2-3 of the response echo the sub-command sent in the request.
 * The response has no documented checksum; the framing check below
 * (magic + cmd + sub-cmd echo) is sufficient to reject unrelated
 * reports that share the boot-mouse hidraw node.
 *
 * The byte at offset 8 has been observed to carry the percentage
 * (e.g. 0x28 = 40%). The charge-state semantics of the response are
 * NOT documented; callers must not claim charging/full from V3 data
 * (see device_profile.c / k99_v3_charge_state). */
#define MCHOSE_K99_V3_REPORT_LEN 64

/* Build the 64-byte V3 battery read request into `out`. Returns
 * MCHOSE_K99_V3_REPORT_LEN on success, -1 if `out` is NULL or the
 * buffer is too small. */
int mk_k99v3_request_build(uint8_t *out, size_t out_len);

/* Parse a 64-byte V3 response. On success returns 0 and writes the
 * percentage (0-100) into *pct, an opaque status byte (semantics
 * unknown; do NOT interpret as charging) into *status, and sets
 * *checksum_ok to 1 (V3 has no checksum). Returns -1 on invalid
 * length, magic, command, sub-command echo, or percentage range. */
int mk_k99v3_response_parse(const uint8_t *buf, size_t len,
                           int *pct, uint8_t *status,
                           int *checksum_ok);

#endif /* MCHOSE_K99_PROTOCOL_H */
