import { Fragment } from "react";

export function plainMailBody(value: string) {
  // Most API bodies are already text. Preserve literal <addresses> and &entities.
  if (!/<\/?(?:html|body|head|p|div|br|table|tr|td|a|img|script|style)\b[^>]*>/i.test(value)) return value;
  const doc = new DOMParser().parseFromString(value || "", "text/html");
  doc.querySelectorAll("script,style,img,iframe,object,noscript,head").forEach((e) => e.remove());
  doc.querySelectorAll("br,p,div,tr,li").forEach((e) => e.append("\n"));
  return doc.body.textContent || "";
}

function bodyParts(value: string) {
  const text = plainMailBody(value || "");
  const parts: { text: string; href?: string }[] = [];
  let start = 0;
  for (const match of text.matchAll(/https?:\/\/[^\s<>"']+/gi)) {
    const index = match.index!;
    let url = match[0].replace(/[.,;!?]+$/, "");
    while (url.endsWith(")") && (url.match(/\)/g)?.length || 0) > (url.match(/\(/g)?.length || 0)) url = url.slice(0, -1);
    try {
      const parsed = new URL(url);
      parts.push({ text: text.slice(start, index) });
      parts.push({ text: url.length > 100 ? `链接：${parsed.hostname}` : url, href: url });
      start = index + url.length;
    } catch { /* Leave malformed URLs as ordinary text. */ }
  }
  parts.push({ text: text.slice(start) });
  return parts;
}

export function readableMailText(value: string) {
  return bodyParts(value).map((part) => part.text).join("");
}

export function MailBody({ value }: { value: string }) {
  return <>{bodyParts(value).map((part, index) => part.href
    ? <a key={index} className="mail-body-link" href={part.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{part.text}</a>
    : <Fragment key={index}>{part.text}</Fragment>)}</>;
}
