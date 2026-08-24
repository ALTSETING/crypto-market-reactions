import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SourceTypeBadge } from "./source-type-badge";


describe("SourceTypeBadge", () => {
  it.each([
    ["news_media", "News media"],
    ["primary_document", "Primary document"],
    ["official_announcement", "Official announcement"],
  ] as const)("renders %s as a friendly label", (sourceType, label) => {
    const markup = renderToStaticMarkup(<SourceTypeBadge sourceType={sourceType} />);
    expect(markup).toContain(label);
    expect(markup).not.toContain(`>${sourceType}<`);
  });
});
