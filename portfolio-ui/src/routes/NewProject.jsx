import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { ArrowRight, Loader2 } from 'lucide-react';

export function NewProject() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState('');
  const [questions, setQuestions] = useState(null);
  const [answers, setAnswers] = useState({});
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const handleClarify = async () => {
    if (!idea.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.clarifyIdea(idea);
      setQuestions(data.questions);
      const initial = {};
      data.questions.forEach((q, i) => { initial[i] = ''; });
      setAnswers(initial);
    } catch (e) {
      setError(`Couldn't fetch the questions: ${e.message}`);
    }
    setLoading(false);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const formattedAnswers = {};
      questions.forEach((q, i) => { formattedAnswers[q] = answers[i]; });
      const data = await api.generateStoryboard(idea, formattedAnswers);
      navigate(`/project/${data.project_id}`);
    } catch (e) {
      setError(`The breakdown failed: ${e.message}`);
      setGenerating(false);
    }
  };

  const updateAnswer = (idx, value) => {
    setAnswers((prev) => ({ ...prev, [idx]: value }));
  };

  const unanswered = questions
    ? questions.filter((_, i) => !(answers[i] || '').trim()).length
    : 0;

  return (
    <div className="max-w-2xl mx-auto px-5 py-10">
      <div className="mb-8 pb-4 border-b border-line">
        <p className="label-slug mb-1.5">Development</p>
        <h1 className="font-mono text-2xl font-bold text-fg mb-2">New storyboard</h1>
        <p className="text-sm text-fg-muted">
          Describe the film. You'll answer a few questions about it, then get a scene
          breakdown with cast, locations, props and a draft shot list.
        </p>
      </div>

      {/* These two steps are a real sequence — you can't answer questions that
          don't exist yet — so they carry ordinal markers. */}
      <section className="mb-4 rounded-frame border border-line bg-bay-850">
        <header className="flex items-center gap-2.5 px-4 py-3 border-b border-line">
          <span className="font-mono text-[11px] font-bold text-lead-500">01</span>
          <h2 className="text-sm font-semibold text-fg">The idea</h2>
        </header>
        <div className="p-4">
          <textarea
            className="w-full bg-bay-900 border border-line rounded-frame p-3 font-mono text-[13px] leading-relaxed text-fg placeholder:text-fg-faint focus:outline-none focus:border-lead-500 resize-y min-h-[130px]"
            placeholder="A noir detective story set in 1980s Tokyo, where a hacker uncovers a corporate conspiracy…"
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
          />
          <button
            onClick={handleClarify}
            disabled={loading || !idea.trim()}
            className="mt-3 flex items-center gap-1.5 px-3 py-2 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors disabled:bg-bay-700 disabled:text-fg-faint"
          >
            {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {loading ? 'Reading it back…' : 'Ask me about it'}
          </button>
        </div>
      </section>

      {questions && (
        <section className="rounded-frame border border-line bg-bay-850">
          <header className="flex items-center gap-2.5 px-4 py-3 border-b border-line">
            <span className="font-mono text-[11px] font-bold text-lead-500">02</span>
            <h2 className="text-sm font-semibold text-fg">The details</h2>
            <span className="ml-auto font-mono text-[11px] text-fg-faint">
              {questions.length - unanswered}/{questions.length}
            </span>
          </header>

          <div className="divide-y divide-line">
            {questions.map((q, i) => (
              <div key={i} className="px-4 py-3.5">
                <label className="block">
                  <span className="block text-[13px] text-fg-muted mb-2">{q}</span>
                  <input
                    className="w-full bg-bay-900 border border-line rounded-frame px-2.5 py-2 font-mono text-[13px] text-fg placeholder:text-fg-faint focus:outline-none focus:border-lead-500"
                    placeholder="Your answer"
                    value={answers[i]}
                    onChange={(e) => updateAnswer(i, e.target.value)}
                  />
                </label>
              </div>
            ))}
          </div>

          <div className="p-4 border-t border-line">
            <button
              onClick={handleGenerate}
              disabled={generating || unanswered > 0}
              className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-frame bg-lead-500 text-bay-950 text-xs font-semibold hover:bg-lead-400 transition-colors disabled:bg-bay-700 disabled:text-fg-faint"
            >
              {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
              {generating ? 'Breaking down the story…' : 'Build the storyboard'}
            </button>
            {unanswered > 0 && !generating && (
              <p className="mt-2 text-center text-[11px] text-fg-faint">
                {unanswered} question{unanswered > 1 ? 's' : ''} still to answer.
              </p>
            )}
          </div>
        </section>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-frame border border-stop/40 bg-stop/10 px-3 py-2 text-xs text-stop">
          {error}
        </p>
      )}
    </div>
  );
}
