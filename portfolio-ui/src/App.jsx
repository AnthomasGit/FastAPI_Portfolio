import { useState } from 'react';

function App() {
  // State tracking
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("idle"); // idle, processing, completed, error
  const [imageUrl, setImageUrl] = useState(null);
  const [warmedUp, setWarmedUp] = useState(false);

  // 1. Fire-and-Forget Warmup
  const handleWarmup = () => {
    if (warmedUp) return; // Only do this once

    fetch("api/portfolio/warmup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: "imagegen" })
    }).catch(console.error); // Silently fail if server is down

    setWarmedUp(true);
  };

  // 2. The Core Generation & Polling Loop
  const handleGenerate = async () => {
    if (!query.trim()) return;

    setStatus("processing");
    setImageUrl(null);

    try {
      // Step A: Submit the job
      const generateRes = await fetch("api/portfolio/imagegen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_name: "imagegen", query: query })
      });

      const generateData = await generateRes.json();
      if (!generateRes.ok) throw new Error(generateData.detail || "Failed to start");

      const jobId = generateData.job_id;

      // Step B: Poll for status every 2 seconds
      const poll = setInterval(async () => {
        const statusRes = await fetch(`api/portfolio/status/${jobId}`);
        const statusData = await statusRes.json();

        if (statusData.status === "completed") {
          clearInterval(poll);
          // Append a timestamp so the browser doesn't load a cached image
          setImageUrl(`api${statusData.download_url}?t=${new Date().getTime()}`);
          setStatus("completed");
        } else if (statusData.status === "failed") {
          clearInterval(poll);
          setStatus("error");
        }
      }, 2000);

    } catch (error) {
      console.error(error);
      setStatus("error");
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white flex flex-col items-center p-10 font-sans">

      <header className="mb-10 text-center">
        <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300 mb-3">
          Z-Turbo Image Generator
        </h1>
        <p className="text-slate-400">Powered by FastAPI & ComfyUI on K3s</p>
      </header>

      <main className="w-full max-w-2xl bg-slate-800 rounded-2xl shadow-2xl p-8 border border-slate-700">

        {/* Input Section */}
        <div className="flex flex-col gap-4 mb-8">
          <textarea
            className="w-full bg-slate-900 border border-slate-600 rounded-lg p-4 text-slate-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none transition-all"
            rows="3"
            placeholder="Describe the image you want to generate..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={handleWarmup} // Wakes up the GPU the second they click!
          />

          <button
            onClick={handleGenerate}
            disabled={status === "processing" || !query.trim()}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-bold py-3 px-6 rounded-lg transition-colors shadow-lg"
          >
            {status === "processing" ? "Generating (Polling Server)..." : "Generate Image"}
          </button>
        </div>

        {/* Dynamic Image Display Area */}
        <div className="bg-slate-900 rounded-lg min-h-[400px] flex items-center justify-center border border-slate-700 overflow-hidden">

          {status === "idle" && (
            <p className="text-slate-500 italic">Your generated image will appear here</p>
          )}

          {status === "processing" && (
            <div className="flex flex-col items-center animate-pulse">
              <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
              <p className="text-blue-400 font-semibold">Warming up GPUs and diffusing latents...</p>
            </div>
          )}

          {status === "completed" && imageUrl && (
            <img
              src={imageUrl}
              alt="Generated output"
              className="w-full h-auto object-contain animate-fade-in"
            />
          )}

          {status === "error" && (
            <p className="text-red-400 font-semibold">Generation failed. Check backend logs.</p>
          )}

        </div>
      </main>

    </div>
  );
}

export default App;