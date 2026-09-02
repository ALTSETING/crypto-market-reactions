interface SeoJsonLdProps {
  data: Record<string, unknown> | Array<Record<string, unknown>>;
}

export function SeoJsonLd({ data }: SeoJsonLdProps) {
  return (
    <script
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
      type="application/ld+json"
    />
  );
}
