import Foundation

struct GPXPoint {
    let lat: Double
    let lon: Double
    let ele: Double?
    let time: Double
    let speed: Double?
}

final class GPXParser: NSObject, XMLParserDelegate {
    private var points: [GPXPoint] = []
    private var currentLat: Double?
    private var currentLon: Double?
    private var currentEle: Double?
    private var currentTime: Date?
    private var currentSpeed: Double?
    private var currentElement: String = ""
    private let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private var fallbackFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
        f.timeZone = TimeZone(secondsFromGMT: 0)
        return f
    }()
    
    func parse(data: Data) throws -> [GPXPoint] {
        points.removeAll()
        let parser = XMLParser(data: data)
        parser.delegate = self
        if !parser.parse() {
            throw parser.parserError ?? NSError(domain: "gpx", code: -1)
        }
        let t0 = points.first?.time ?? 0
        return points.map { GPXPoint(lat: $0.lat, lon: $0.lon, ele: $0.ele, time: $0.time - t0, speed: $0.speed) }
    }
    
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes attributeDict: [String : String] = [:]) {
        currentElement = elementName
        if elementName == "trkpt" {
            currentLat = Double(attributeDict["lat"] ?? "")
            currentLon = Double(attributeDict["lon"] ?? "")
            currentEle = nil
            currentTime = nil
            currentSpeed = nil
        }
    }
    
    func parser(_ parser: XMLParser, foundCharacters string: String) {
        let s = string.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return }
        switch currentElement {
        case "ele":
            currentEle = Double(s)
        case "time":
            if let d = isoFormatter.date(from: s) ?? fallbackFormatter.date(from: s) {
                currentTime = d
            }
        case "gpxtpx:speed", "ns3:speed", "speed":
            if let v = Double(s) {
                currentSpeed = v * 3.6
            }
        default:
            break
        }
    }
    
    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        if elementName == "trkpt" {
            if let la = currentLat, let lo = currentLon, let t = currentTime {
                let pt = GPXPoint(lat: la, lon: lo, ele: currentEle, time: t.timeIntervalSince1970, speed: currentSpeed)
                points.append(pt)
            }
        }
        currentElement = ""
    }
}
