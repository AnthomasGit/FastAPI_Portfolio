import { FileText } from 'lucide-react';

export function StorySummary({ summary }) {
  if (!summary) return null;

  return (
    <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="w-4 h-4 text-cyan-400" />
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Story Summary</h2>
      </div>
      <p className="text-slate-300 leading-relaxed text-sm">{summary}</p>
    </div>
  );
}
