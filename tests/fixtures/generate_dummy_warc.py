import gzip
import io
import time

def create_warc_record(url, content_type, body):
    date = "2024-04-26T12:00:00Z"
    warc_headers = (
        f"WARC/1.0\r\n"
        f"WARC-Type: response\r\n"
        f"WARC-Target-URI: {url}\r\n"
        f"WARC-Date: {date}\r\n"
        f"WARC-Identified-Payload-Type: {content_type}\r\n"
        f"WARC-Record-ID: <urn:uuid:{time.time()}>\r\n"
        f"Content-Type: application/http; msgtype=response\r\n"
    )
    
    http_headers = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Server: Dummy\r\n"
        f"\r\n"
    )
    
    full_body = http_headers.encode('utf-8') + body
    warc_headers += f"Content-Length: {len(full_body)}\r\n\r\n"
    
    return warc_headers.encode('utf-8') + full_body + b"\r\n\r\n"

def generate_sample_warc(output_path, num_records=1000):
    with gzip.open(output_path, 'wb') as f:
        # warcinfo
        f.write(b"WARC/1.0\r\nWARC-Type: warcinfo\r\nContent-Length: 10\r\n\r\nDummy info\r\n\r\n")
        
        for i in range(num_records):
            domain = "google.com" if i % 2 == 0 else "facebook.com"
            r = i % 10
            if r < 7:
                url = f"http://{domain}/assets/img{i}.jpg"
                ct = "image/jpeg"
                body = b"fake-image-data" * 100
            elif r < 9:
                url = f"http://{domain}/page{i}.html"
                ct = "text/html"
                if i % 2 == 0:
                    body = b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed"></head><body>hello</body></html>'
                else:
                    body = b'<html><head><title>No feed</title></head><body>hello</body></html>'
                body += b"padding" * 500
            else:
                url = f"http://{domain}/feed{i}.xml"
                ct = "application/rss+xml"
                body = b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Feed</title><item><title>Entry</title></item></channel></rss>'
                body += b"padding" * 200
            
            f.write(create_warc_record(url, ct, body))

if __name__ == "__main__":
    generate_sample_warc("tests/fixtures/profile_sample.warc.gz", 20000)
