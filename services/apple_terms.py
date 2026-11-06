"""Read the terms document returned by Apple's getTerms endpoint."""
import base64
import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser


class TermsText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.links = []
        self.lists = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.hidden += 1
        if self.hidden:
            return
        if tag in ("ol", "ul"):
            start = dict(attrs).get("start", "1")
            self.lists.append(int(start) - 1 if tag == "ol" and start.isdigit() else None)
        if tag in ("p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "li"):
            self.parts.append("\n")
        if tag == "li":
            if self.lists and self.lists[-1] is not None:
                self.lists[-1] += 1
                self.parts.append(str(self.lists[-1]) + ". ")
            else:
                self.parts.append("• ")
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag in ("ol", "ul") and self.lists:
            self.lists.pop()
        if tag == "a" and self.links:
            link = self.links.pop()
            if link.startswith("https://"):
                self.parts.append(" (" + link + ")")
        if tag in ("p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "li"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append("\t")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)


def readable_text(value, *, escaped_html=False):
    if not isinstance(value, str):
        return ""
    parser = TermsText()
    # GCBD notices can contain entity-escaped markup. Decode that layer before
    # parsing, so tags become paragraphs/links rather than visible source text.
    parser.feed(unescape(value) if escaped_html else value)
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts)).strip()


def terms_document(data, privacy_required=False):
    """Expose only the reviewed document, never other upstream response fields."""
    if not isinstance(data, dict) or not isinstance(data.get("iCloudTerms"), dict):
        raise ValueError("Apple 未返回可阅读的条款，请重新加载。")
    terms = data["iCloudTerms"]
    version = terms.get("version")
    content = terms.get("content")
    if type(version) is not int or version <= 0 or not isinstance(content, str) or len(content) > 1_000_000:
        raise ValueError("Apple 返回的条款格式不完整，请重新加载。")
    # Apple's web client decodes these three UTF-8 base64 fields. The GCBD
    # privacy notice is already plain HTML/text and must not be base64-decoded.
    decoded = {key: base64.b64decode(terms.get(key, ""), validate=True).decode("utf-8")
               for key in ("title", "summary", "content")}
    document = {
        "version": version,
        "title": readable_text(decoded["title"]) or "iCloud 条款与条件",
        "summary": readable_text(decoded["summary"]),
        "content": readable_text(decoded["content"]),
        "privacy_title": readable_text(data.get("gcbdPrivacyNoticeTitle"), escaped_html=True),
        "privacy_content": readable_text(data.get("gcbdPrivacyNoticeMessage"), escaped_html=True),
        "privacy_required": bool(privacy_required or data.get("gcbdPrivacyNoticeMessage")),
    }
    if not document["content"] or document["privacy_required"] and not document["privacy_content"]:
        raise ValueError("Apple 返回的条款或隐私告知不完整，请重新加载。")
    # Bind consent to the exact upstream document, including its version and
    # any separately required privacy notice. A changed document needs consent.
    fingerprint = {"terms": terms, "privacy_required": document["privacy_required"],
                   "privacy_title": data.get("gcbdPrivacyNoticeTitle"),
                   "privacy_content": data.get("gcbdPrivacyNoticeMessage")}
    document["document_id"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return document
