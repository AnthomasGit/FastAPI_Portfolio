export function StorySummary({ summary }) {
  if (!summary) return null;

  return (
    <section className="mb-5 rounded-frame border border-line bg-bay-850 p-4">
      <p className="label-slug mb-2">Logline</p>
      <p className="font-mono text-[13px] leading-relaxed text-fg-muted max-w-3xl">{summary}</p>
    </section>
  );
}
