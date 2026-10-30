#include "CompxProtocol.h"

namespace compx {

QByteArray request(uint8_t command, uint16_t address, uint8_t length, const QByteArray &data)
{
    QByteArray r(PayloadSize + 1, '\0');
    r[0] = char(ReportId);
    r[1] = char(command);
    r[3] = char(address >> 8);
    r[4] = char(address & 0xFF);
    r[5] = char(length);
    for (int i = 0; i < data.size() && i < MaxData; ++i)
        r[6 + i] = data[i];
    uint8_t sum = ReportId;
    for (int i = 1; i < PayloadSize; ++i)
        sum = uint8_t(sum + uint8_t(r[i]));
    r[PayloadSize] = char(uint8_t(0x55 - sum));
    return r;
}

bool checksumValid(const QByteArray &report)
{
    if (report.size() < PayloadSize + 1)
        return false;
    uint8_t sum = 0;
    for (int i = 0; i <= PayloadSize; ++i)
        sum = uint8_t(sum + uint8_t(report[i]));
    return sum == 0x55;
}

QByteArray pair(uint8_t v)
{
    QByteArray b(2, '\0');
    b[0] = char(v);
    b[1] = char(pairCrc(v));
    return b;
}

std::optional<uint8_t> unpair(const QByteArray &block, int offset)
{
    if (offset + 1 >= block.size())
        return std::nullopt;
    const uint8_t v = uint8_t(block[offset]);
    if (uint8_t(block[offset + 1]) != pairCrc(v))
        return std::nullopt;
    return v;
}

static void encodeAxis(int dpi, Codec codec, uint8_t &lo, uint8_t &hi, uint8_t &flags, int axisShift)
{
    int idx = 0;
    flags = 0;
    if (codec == Codec::Paw3950Ultra) {
        if (dpi <= 10000) {
            idx = dpi / 10 - 1;
        } else {
            const int base = dpi <= 30000 ? dpi : dpi / 2;
            idx = (base - 10050) / 50;
            flags |= uint8_t(0x02 << axisShift);
            if (dpi > 30000)
                flags |= uint8_t(0x01 << axisShift);
        }
    } else {
        if (dpi > 30000) {
            idx = dpi / 100 - 1;
            flags |= uint8_t(0x01 << axisShift);
        } else {
            idx = dpi / 50 - 1;
        }
    }
    lo = uint8_t(idx & 0xFF);
    hi = uint8_t((idx >> 8) & 3);
}

std::array<uint8_t, 4> encodeDpi(int x, int y, Codec codec)
{
    uint8_t xl, xh, xf, yl, yh, yf;
    encodeAxis(x, codec, xl, xh, xf, 0);
    encodeAxis(y, codec, yl, yh, yf, 4);
    const uint8_t ex = uint8_t((yh << 6) | (xh << 2) | xf | yf);
    return {xl, yl, ex, uint8_t(0x55 - (xl + yl + ex))};
}

int decodeDpiX(const uint8_t *stage, Codec codec)
{
    const uint8_t ex = stage[2];
    const int v = stage[0] | (((ex & 0x0C) >> 2) << 8);
    int dpi;
    if (codec == Codec::Paw3950Ultra)
        dpi = (ex & 0x02) ? v * 50 + 10050 : (v + 1) * 10;
    else
        dpi = (v + 1) * 50;
    if (ex & 0x01)
        dpi *= 2;
    return dpi;
}

int dpiMin(Codec codec)
{
    return codec == Codec::Paw3395 ? 100 : 50;
}

int dpiMax(Codec codec)
{
    return codec == Codec::Paw3395 ? 30000 : 36000;
}

int dpiStep(Codec codec, int dpi)
{
    if (codec == Codec::Paw3950Ultra && dpi <= 10000)
        return 10;
    return dpi > 30000 ? 100 : 50;
}

int pollingRateFromCode(uint8_t code)
{
    switch (code) {
    case 0x01: return 1000;
    case 0x02: return 500;
    case 0x04: return 250;
    case 0x08: return 125;
    case 0x10: return 2000;
    case 0x20: return 4000;
    case 0x40: return 8000;
    }
    return 0;
}

uint8_t pollingRateCode(int hz)
{
    switch (hz) {
    case 1000: return 0x01;
    case 500: return 0x02;
    case 250: return 0x04;
    case 125: return 0x08;
    case 2000: return 0x10;
    case 4000: return 0x20;
    case 8000: return 0x40;
    }
    return 0;
}

}
