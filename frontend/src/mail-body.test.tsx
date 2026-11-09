import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MailBody, plainMailBody, readableMailText } from "./lib/mail-body";

describe("readable mail bodies", () => {
  it("shortens long tracking links while preserving text, line breaks and the exact link target", () => {
    const url = "https://tracking.example.test/click?token=" + "encoded-token-".repeat(140);
    const body = `开头\n(${url})\n完整的正文结尾。`;
    const { container } = render(<MailBody value={body} />);
    expect(container.textContent).toBe("开头\n(链接：tracking.example.test)\n完整的正文结尾。");
    const link = screen.getByRole("link", { name: "链接：tracking.example.test" });
    expect(link.getAttribute("href")).toBe(url);
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(readableMailText(body)).not.toContain("encoded-token");
    expect(plainMailBody(body)).toBe(body);
  });

  it("keeps literal text and short links intact", () => {
    const text = "收件人 <mail@example.test> &amp; 中文 café\nhttps://example.test/a_(b).";
    expect(plainMailBody(text)).toBe(text);
    const { container } = render(<MailBody value={text} />);
    expect(container.textContent).toBe(text);
    expect(screen.getByRole("link").getAttribute("href")).toBe("https://example.test/a_(b)");
  });

  it("renders HTML as inert text without remote images, styles or executable links", () => {
    const body = '<html><head><style>hidden-css</style></head><body><p>可读内容</p><img src="https://track.example.test/pixel"><script>alert(1)</script><a href="javascript:alert(1)">普通文字</a></body></html>';
    const { container } = render(<MailBody value={body} />);
    expect(container.textContent).toContain("可读内容");
    expect(container.textContent).toContain("普通文字");
    expect(container.textContent).not.toContain("alert(1)");
    expect(container.querySelector("img,script,iframe,style,a")).toBeNull();
  });
});
