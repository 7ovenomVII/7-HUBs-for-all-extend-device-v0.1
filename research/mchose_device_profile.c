/* Device-profile registry for MCHOSE HID battery bridges.
 *
 * Each profile in mchose_profiles[] bundles the matching data, wire
 * protocol, charge-state mapping, and virtual UHID presentation for
 * one MCHOSE device generation. Adding a new device = append a
 * profile here. The legacy K99 must stay first to preserve its
 * historical "Compx 2.4G Wireless Receiver" sysfs signature.
 */

#define _GNU_SOURCE
#include "device_profile.h"
#include "protocol.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ----- Legacy K99 (Compx 2.4G receiver, 20-byte vendor report). ----- */

static const char *const k99_legacy_name_tokens[] = {
    "Compx",
    "2.4G Wireless Receiver",
};

static const uint8_t k99_legacy_frag_vendor[]   = { 0x06, 0x02, 0xff };
static const uint8_t k99_legacy_frag_report_id[] = { 0x85, 0x13 };
static const uint8_t *const k99_legacy_desc_fragments[] = {
    k99_legacy_frag_vendor,
    k99_legacy_frag_report_id,
};
static const size_t k99_legacy_desc_fragment_lens[] = {
    sizeof(k99_legacy_frag_vendor),
    sizeof(k99_legacy_frag_report_id),
};
/* The 20-byte vendor report shape. The legacy K99 receiver exposes
 * multiple HID interfaces with the same HID_ID; this fragment is
 * what distinguishes the battery vendor interface from the keyboard
 * interface (which has a different report count). */
static const uint8_t k99_legacy_exact_fragment[] = {
    0x85, 0x13, 0x15, 0x00, 0x26, 0xff, 0x00, 0x75, 0x08, 0x95, 0x13,
};

static int k99_legacy_build(uint8_t *out, size_t out_len)
{
    if (out_len < MCHOSE_REPORT_LEN)
        return -1;
    return mk_request_build(out);
}

static int k99_legacy_parse(const uint8_t *buf, size_t len,
                            int *pct, uint8_t *status, int *cksum_ok)
{
    return mk_response_parse(buf, len, pct, status, cksum_ok);
}

static int k99_legacy_charge(uint8_t status)
{
    return mk_charge_state(status);
}

static const device_profile k99_legacy_profile = {
    .name                     = "k99-legacy",
    .vid_pid                  = "0003:000005AC:0000024F",
    .name_tokens              = k99_legacy_name_tokens,
    .n_name_tokens            = 2,
    .desc_fragments           = k99_legacy_desc_fragments,
    .desc_fragment_lens       = k99_legacy_desc_fragment_lens,
    .n_desc_fragments         = 2,
    .exact_desc_fragment      = k99_legacy_exact_fragment,
    .exact_desc_fragment_len  = sizeof(k99_legacy_exact_fragment),
    .report_len               = MCHOSE_REPORT_LEN,
    .build_request            = k99_legacy_build,
    .parse_response           = k99_legacy_parse,
    .charge_state             = k99_legacy_charge,
    .vb_product               = 0x024F,
    .vb_name                  = "MCHOSE K99 Battery",
};

/* ----- K99 V3 (MCHOSE 0x3837 / 0x3033, 64-byte raw IN+OUT). ----- */

static const char *const k99_v3_name_tokens[] = {
    "MCHOSE",
    "K99 V3",
};

/* The K99 V3 receiver exposes two USB HID interfaces that share the
 * same HID_ID and HID_NAME strings:
 *
 *   interface 0: HID 1.1 boot mouse.
 *                Usage Page = Generic Desktop, Usage = Mouse (0x02),
 *                INPUT-only (no Output endpoint), short reports.
 *                This is what BIOS / pre-boot environments use.
 *
 *   interface 1: a HID 1.1 generic-desktop interface with
 *                Usage = Undefined (0x00), 64-byte Data/Variable/
 *                Absolute IN+OUT reports. THIS is the K99 V3
 *                battery channel.
 *
 * A previous version of this profile used the boot-mouse signature
 * (09 02 a1 01) and therefore matched interface 0; the kernel then
 * opened a node with no OUT endpoint and the 64-byte write returned
 * nothing, producing a 5-second timeout. The fragments below all
 * reference interface 1's descriptor and require all three to be
 * present, so a node with any one missing (in particular the boot
 * mouse, which lacks 91 02 entirely) is rejected. */
static const uint8_t k99_v3_frag_app_header[] = {
    /* Generic Desktop / Usage Undefined / Application Collection.
     * Boot mouse has `09 02 a1 01` instead. */
    0x09, 0x00, 0xA1, 0x01,
};
static const uint8_t k99_v3_frag_64b_report[] = {
    /* Report Count 64, Report Size 8 => 64-byte field. The boot
     * mouse uses Report Count 3/1/2 instead of 64. */
    0x95, 0x40, 0x75, 0x08,
};
static const uint8_t k99_v3_frag_output_endpoint[] = {
    /* Output (Data, Variable, Absolute). The boot mouse has no
     * Output endpoint at all (no 0x91 byte anywhere in its
     * descriptor). This is the decisive differentiator: without
     * an OUT endpoint we cannot write the 64-byte query. */
    0x91, 0x02,
};
static const uint8_t *const k99_v3_desc_fragments[] = {
    k99_v3_frag_app_header,
    k99_v3_frag_64b_report,
    k99_v3_frag_output_endpoint,
};
static const size_t k99_v3_desc_fragment_lens[] = {
    sizeof(k99_v3_frag_app_header),
    sizeof(k99_v3_frag_64b_report),
    sizeof(k99_v3_frag_output_endpoint),
};

static int k99_v3_build(uint8_t *out, size_t out_len)
{
    return mk_k99v3_request_build(out, out_len);
}

static int k99_v3_parse(const uint8_t *buf, size_t len,
                        int *pct, uint8_t *status, int *cksum_ok)
{
    return mk_k99v3_response_parse(buf, len, pct, status, cksum_ok);
}

static int k99_v3_charge(uint8_t status)
{
    /* K99 V3 charge-state semantics are UNKNOWN.
     *
     * The legacy K99 carries a documented status byte (charging bit
     * 0x10, "ready" bit 0x01). The V3 byte at the same offset does
     * not map to those bits: M HUB does not expose a charging
     * indicator for V3, and we have no firmware documentation for
     * the byte.
     *
     * To avoid falsely reporting "charging" or "fully charged" at
     * the UPower layer (which would prevent the OS from putting the
     * device to sleep and would mislabel the battery state), we
     * conservatively return 0 (discharging) for every input. Once
     * V3 semantics are confirmed by further captures, replace this
     * with the real mapping. */
    (void)status;
    return 0;
}

static const device_profile k99_v3_profile = {
    .name                     = "k99-v3",
    .vid_pid                  = "0003:00003837:00003033",
    .name_tokens              = k99_v3_name_tokens,
    .n_name_tokens            = 2,
    .desc_fragments           = k99_v3_desc_fragments,
    .desc_fragment_lens       = k99_v3_desc_fragment_lens,
    .n_desc_fragments         = 3,
    .exact_desc_fragment      = NULL,
    .exact_desc_fragment_len  = 0,
    .report_len               = MCHOSE_K99_V3_REPORT_LEN,
    .build_request            = k99_v3_build,
    .parse_response           = k99_v3_parse,
    .charge_state             = k99_v3_charge,
    .vb_product               = 0x3033,
    .vb_name                  = "MCHOSE K99 V3 Battery",
};

/* ----- Registry. ----- */

const device_profile *const mchose_profiles[] = {
    &k99_legacy_profile,
    &k99_v3_profile,
};
const size_t mchose_n_profiles =
    sizeof(mchose_profiles) / sizeof(mchose_profiles[0]);

/* ----- Matching. ----- */

static bool contains_bytes(const uint8_t *hay, size_t hay_len,
                           const uint8_t *needle, size_t needle_len)
{
    if (needle_len > hay_len)
        return false;
    for (size_t i = 0; i + needle_len <= hay_len; i++) {
        if (memcmp(hay + i, needle, needle_len) == 0)
            return true;
    }
    return false;
}

static bool name_tokens_match(const device_profile *p, const char *name_blob)
{
    for (size_t i = 0; i < p->n_name_tokens; i++) {
        if (!p->name_tokens[i])
            return false;
        if (!strstr(name_blob, p->name_tokens[i]))
            return false;
    }
    return true;
}

static bool desc_fragments_match(const device_profile *p,
                                 const uint8_t *desc, size_t desc_len)
{
    for (size_t i = 0; i < p->n_desc_fragments; i++) {
        if (!contains_bytes(desc, desc_len,
                            p->desc_fragments[i],
                            p->desc_fragment_lens[i]))
            return false;
    }
    return true;
}

const device_profile *mchose_profile_match(const char *hid_id,
                                           const char *name_blob,
                                           const uint8_t *desc,
                                           size_t desc_len)
{
    if (!hid_id || !name_blob || !desc)
        return NULL;
    for (size_t i = 0; i < mchose_n_profiles; i++) {
        const device_profile *p = mchose_profiles[i];
        if (strcmp(hid_id, p->vid_pid) != 0)
            continue;
        if (!name_tokens_match(p, name_blob))
            continue;
        if (!desc_fragments_match(p, desc, desc_len))
            continue;
        return p;
    }
    return NULL;
}