import csv
import importlib
import io
import ipaddress
import re
import socket
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from storage import atomic_write, digest, now, read_json, read_text, write_json


MAX_BYTES = 8_000_000
TRUST_LEVELS = ("public", "own", "synthetic")


class PageText(HTMLParser):
    hidden_tags = {"script", "style", "template", "noscript", "svg"}
    block_tags = {"article", "section", "div", "p", "li", "h1", "h2", "h3", "tr", "br"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden_tags:
            self.hidden.append(tag)
        elif tag in self.block_tags and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif tag in self.block_tags and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_text(data):
    parser = PageText()
    parser.feed(data)
    parser.close()
    return parser.text()


def document_text(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Файл превышает 8 МБ.")
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return "document", read_text(path)
    if suffix == ".csv":
        rows = csv.reader(io.StringIO(read_text(path)))
        return "table", "\n".join(
            f"Строка {number}: " + " | ".join(cell.replace("\n", " ") for cell in row)
            for number, row in enumerate(rows, 1)
        )
    if suffix in {".html", ".htm"}:
        return "web", html_text(read_text(path))
    if suffix == ".docx":
        with zipfile.ZipFile(path) as document:
            member = document.getinfo("word/document.xml")
            if member.file_size > MAX_BYTES:
                raise ValueError("Текст DOCX превышает 8 МБ.")
            tree = ElementTree.fromstring(document.read(member))
        return "document", "\n".join(
            "".join(node.text or "" for node in paragraph.iterfind(".//{*}t"))
            for paragraph in tree.iterfind(".//{*}p")
        )
    if suffix == ".xlsx":
        try:
            openpyxl = importlib.import_module("openpyxl")
        except ImportError as error:
            raise ValueError("Для XLSX установите openpyxl или сохраните листы как CSV.") from error
        with zipfile.ZipFile(path) as archive:
            if sum(member.file_size for member in archive.infolist()) > 32_000_000:
                raise ValueError("Распакованный XLSX превышает 32 МБ.")
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            lines = []
            for sheet in workbook.worksheets:
                if (sheet.max_row or 0) * (sheet.max_column or 0) > 250_000:
                    raise ValueError("Лист XLSX превышает 250 000 ячеек. Выгрузите нужный диапазон.")
                lines.append(f"Лист {sheet.title}")
                for number, row in enumerate(sheet.values, 1):
                    if any(cell is not None for cell in row):
                        cells = [str(cell).replace("\n", " ") if cell is not None else "" for cell in row]
                        lines.append(f"Строка {number}: " + " | ".join(cells))
            return "table", "\n".join(lines)
        finally:
            workbook.close()
    if suffix == ".pdf":
        try:
            pypdf = importlib.import_module("pypdf")
        except ImportError as error:
            raise ValueError("Для PDF установите pypdf или передайте текстовую выгрузку.") from error
        reader = pypdf.PdfReader(path)
        if len(reader.pages) > 100:
            raise ValueError("PDF превышает 100 страниц. Передайте нужный раздел.")
        pages = [page.extract_text() or "" for page in reader.pages]
        if not any(page.strip() for page in pages):
            raise ValueError("В PDF нет текстового слоя. Передайте текст после OCR.")
        return "document", "\n\n".join(f"Страница {i}\n{text}" for i, text in enumerate(pages, 1))
    raise ValueError("Поддерживаются TXT, MD, DOCX, CSV, HTML, XLSX и текстовые PDF.")


def checked_url(url, allowed_hosts, check_dns=False):
    parsed = urlsplit(url)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or host not in allowed_hosts
        or "." not in host
    ):
        raise ValueError("Нужен HTTPS-адрес на явно разрешённом публичном домене.")
    if check_dns:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
            raise ValueError("Адрес источника не является публичным.")
    return url


class AllowedRedirect(HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, self.allowed_hosts, check_dns=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, hosts):
    checked_url(url, hosts, check_dns=True)
    request = Request(url, headers={"User-Agent": "ProductStrategist/1.0", "Accept": "text/html,text/plain"})
    with build_opener(AllowedRedirect(hosts)).open(request, timeout=15) as response:
        mime = response.headers.get_content_type()
        if mime not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise ValueError("Скачивание поддерживает HTML и обычный текст. Документ импортируйте как файл.")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Ответ сайта превышает 8 МБ.")
        body = data.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        return response.geturl(), html_text(body) if mime != "text/plain" else body


def source_index(project):
    path = project / "sources" / "index.json"
    return read_json(path) if path.exists() else {}


def add_source(project, args):
    index = source_index(project)
    if args.url:
        hosts = {host.lower() for host in args.allow_host}
        location = checked_url(args.url, hosts)
        cached = [entry for entry in index.values() if entry.get("requested_url") == location]
        if cached and not args.refresh:
            return cached[-1]
        location, content = download(location, hosts)
        kind, trust, capture = "web", "public", "download"
    else:
        path = Path(args.file)
        kind, content = document_text(path)
        location = args.origin or path.name
        trust = args.trust
        capture = "file"
        if args.origin:
            host = urlsplit(args.origin).hostname
            checked_url(args.origin, {host})
            if kind in {"document", "web"}:
                kind, capture = "web", "excerpt"
    content = "\n".join(content.strip().splitlines()) + "\n"
    if not content.strip():
        raise ValueError("Из источника не удалось получить текст.")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Извлечённый текст превышает 8 МБ.")
    title = args.title.strip()
    if not title:
        raise ValueError("Укажите название источника.")
    fingerprint = digest(content)
    key = "S-" + digest(f"{location}\n{trust}\n{fingerprint}")[:12].upper()
    if key in index:
        if args.url and index[key].get("requested_url") != args.url:
            index[key]["requested_url"] = args.url
            write_json(project / "sources" / "index.json", index)
        return index[key]
    snapshot = f"sources/{key}.txt"
    entry = {
        "id": key, "title": title, "origin": location, "kind": kind, "trust": trust,
        "capture": capture, "retrieved_at": now(), "snapshot": snapshot, "sha256": fingerprint,
    }
    if args.url:
        entry["requested_url"] = args.url
    atomic_write(project / snapshot, content)
    index[key] = entry
    write_json(project / "sources" / "index.json", index)
    return entry


def source_lines(project, entry):
    text = read_text(project / entry["snapshot"])
    if digest(text) != entry["sha256"]:
        raise ValueError(f"Контрольная сумма источника {entry['id']} не совпала.")
    return text.splitlines()


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()
