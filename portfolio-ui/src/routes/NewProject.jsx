import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { Sparkles, ArrowRight, Loader2, Lightbulb } from 'lucide-react';

export function NewProject() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState('');
  const [questions, setQuestions] = useState(null);
  const [answers, setAnswers] = useState({});
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  const handleClarify = async () => {
    if (!idea.trim()) return;
    setLoading(true);
    try {
      const data = await api.clarifyIdea(idea);
      setQuestions(data.questions);
      const initial = {};
      data.questions.forEach((q, i) => { initial[i] = ''; });
      setAnswers(initial);
    } catch (e) {
      alert('Failed to get questions: ' + e.message);
    }
    setLoading(false);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const formattedAnswers = {};
      questions.forEach((q, i) => { formattedAnswers[q] = answers[i]; });
      const data = await api.generateStoryboard(idea, formattedAnswers);
      navigate(`/project/${data.project_id}`);
    } catch (e) {
      alert('Failed to generate: ' + e.message);
    }
    setGenerating(false);
  };

  const updateAnswer = (idx, value) => {
    setAnswers((prev) => ({ ...prev, [idx]: value }));
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">New Storyboard</h1>
        <p className="text-slate-400">Enter a rough video idea, then answer clarifying questions to generate your storyboard.</p>
      </div>

      <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center text-sm font-bold text-white">1</div>
          <h2 className="text-lg font-semibold">Describe your video idea</h2>
        </div>
        <textarea
          className="w-full bg-black/40 border border-white/10 rounded-xl p-4 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 resize-none min-h-[120px]"
          placeholder="e.g., A noir detective story set in 1980s Tokyo where a hacker uncovers a corporate conspiracy..."
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
        />
        <button
          onClick={handleClarify}
          disabled={loading || !idea.trim()}
          className="mt-4 flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-medium hover:from-blue-500 hover:to-cyan-400 transition-all disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          Get Clarifying Questions
        </button>
      </div>

      {questions && (
        <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500 to-teal-400 flex items-center justify-center text-sm font-bold text-white">2</div>
            <h2 className="text-lg font-semibold">Answer clarifying questions</h2>
          </div>

          <div className="space-y-4 mb-6">
            {questions.map((q, i) => (
              <div key={i} className="bg-black/30 rounded-xl p-4 border border-white/5">
                <label className="flex items-start gap-3">
                  <Lightbulb className="w-4 h-4 text-amber-400 mt-1 shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm text-slate-300 mb-2">{q}</p>
                    <input
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 text-sm"
                      placeholder="Your answer..."
                      value={answers[i]}
                      onChange={(e) => updateAnswer(i, e.target.value)}
                    />
                  </div>
                </label>
              </div>
            ))}
          </div>

          <button
            onClick={handleGenerate}
            disabled={generating || Object.values(answers).some((a) => !a.trim())}
            className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-medium hover:from-blue-500 hover:to-cyan-400 transition-all disabled:opacity-50"
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
            {generating ? 'Generating Storyboard...' : 'Generate Storyboard'}
          </button>
        </div>
      )}
    </div>
  );
}
