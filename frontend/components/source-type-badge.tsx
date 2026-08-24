import { SOURCE_TYPE_LABELS, type SourceType } from "@/types/events";

const tones: Record<SourceType, string> = {
  news_media: "border-sky-400/25 bg-sky-400/8 text-sky-200",
  primary_document: "border-amber-400/25 bg-amber-400/8 text-amber-200",
  official_announcement: "border-violet-400/25 bg-violet-400/8 text-violet-200",
  unknown: "border-slate-400/25 bg-slate-400/8 text-slate-300",
};

export function SourceTypeBadge({ sourceType }: { sourceType: SourceType }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[sourceType]}`}
      data-source-type={sourceType}
    >
      {SOURCE_TYPE_LABELS[sourceType]}
    </span>
  );
}
