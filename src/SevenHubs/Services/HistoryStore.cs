using System.IO;
using System.Text.Json;
using SevenHubs.Models;

namespace SevenHubs.Services;

public sealed class HistoryStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true
    };

    private readonly string _filePath;
    private readonly string _fallbackPath;

    public HistoryStore()
    {
        var root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(root))
            root = AppContext.BaseDirectory;
        _filePath = Path.Combine(root, "7HUBs", "devices.json");
        _fallbackPath = Path.Combine(AppContext.BaseDirectory, "data", "devices.json");
    }

    public string FilePath => _filePath;

    public Dictionary<string, DeviceRecord> Load()
    {
        var primary = Read(_filePath);
        return primary.Count > 0 ? primary : Read(_fallbackPath);
    }

    private static Dictionary<string, DeviceRecord> Read(string path)
    {
        try
        {
            if (!File.Exists(path))
                return new Dictionary<string, DeviceRecord>(StringComparer.OrdinalIgnoreCase);

            var json = File.ReadAllText(path);
            var records = JsonSerializer.Deserialize<List<DeviceRecord>>(json, JsonOptions) ?? new List<DeviceRecord>();
            return records
                .Where(r => !string.IsNullOrWhiteSpace(r.Id))
                .GroupBy(r => r.Id, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(g => g.Key, g => g.Last(), StringComparer.OrdinalIgnoreCase);
        }
        catch
        {
            return new Dictionary<string, DeviceRecord>(StringComparer.OrdinalIgnoreCase);
        }
    }

    public void Save(IEnumerable<DeviceRecord> records)
    {
        var ordered = records
            .OrderByDescending(r => r.Connected)
            .ThenByDescending(r => r.LastSeen)
            .ToList();
        var json = JsonSerializer.Serialize(ordered, JsonOptions);

        if (TryWrite(_filePath, json))
            return;

        TryWrite(_fallbackPath, json);
    }

    private static bool TryWrite(string path, string json)
    {
        try
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);

            File.WriteAllText(path, json);
            return true;
        }
        catch
        {
            // History is a convenience; never let a disk error break a scan.
            return false;
        }
    }
}
