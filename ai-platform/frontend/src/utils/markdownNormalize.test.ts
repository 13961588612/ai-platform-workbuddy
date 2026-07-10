import { describe, expect, it } from "vitest";
import { normalizeMarkdownTables } from "./markdownNormalize";

describe("normalizeMarkdownTables", () => {
  it("keeps a well-formed table intact", () => {
    const input = [
      "会员汇总如下：",
      "",
      "| 券来源 | 券类型 | 余额(元) | 状态 | 有效期至 |",
      "|------|--------|---------|------|---------|",
      "| 账户券 | 华粉券 | **3.00** | 有效 | 2099-12-31 |",
      "",
      "当前共有 1 张。",
    ].join("\n");

    expect(normalizeMarkdownTables(input)).toBe(input);
  });

  it("splits collapsed rows joined by double pipes", () => {
    const input =
      "| 券来源 | 券类型 | 余额(元) | 状态 | 有效期至 ||-----|------|------|------|----------|| 账户券 | 华粉券 | 3.00 | 有效 | 2099-12-31 |";
    const out = normalizeMarkdownTables(input);
    const lines = out.split("\n");
    expect(lines.length).toBeGreaterThanOrEqual(3);
    expect(lines[0]).toContain("券来源");
    expect(lines[1]).toMatch(/^\|[-|:\s]+\|$/);
    expect(lines[2]).toContain("账户券");
  });

  it("inserts blank line when table is glued after colon", () => {
    const input = "汇总如下：| 字段 | 内容 |\n|------|------|\n| A | B |";
    const out = normalizeMarkdownTables(input);
    expect(out.startsWith("汇总如下：\n\n| 字段 |")).toBe(true);
  });
});
