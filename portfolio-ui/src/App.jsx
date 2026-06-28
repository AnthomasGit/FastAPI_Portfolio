import { useState, useEffect, useRef } from 'react';

function App() {
  // --- EXISTING STATE & LOGIC ---
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("idle");
  const [imageUrl, setImageUrl] = useState(null);
  const [warmedUp, setWarmedUp] = useState(false);
  const [history, setHistory] = useState([]);
  const [workflow, setWorkflow] = useState("imagegen");
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef(null);

  const fetchHistory = async () => {
    try {
      const res = await fetch("/api/portfolio/history");
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch (error) {
      console.error("Failed to fetch history:", error);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleWarmup = () => {
    if (warmedUp) return; // Only do this once

    fetch("api/portfolio/warmup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: workflow })
    }).catch(console.error); // Silently fail if server is down

    setWarmedUp(true);
  };

  // 2. The Core Generation & Polling Loop
  const handleGenerate = async () => {
    if (!query.trim()) return;
    if (workflow === "imageedit" && !selectedFile) {
      alert("Please upload a reference image for the Image Edit workflow.");
      return;
    }

    setStatus("processing");
    setImageUrl(null);

    try {
      let uploadedFilename = null;

      // Step 1 (Optional): Upload the image if in edit mode
      if (workflow === "imageedit" && selectedFile) {
        const formData = new FormData();
        formData.append("file", selectedFile);

        const uploadRes = await fetch("/api/portfolio/upload", {
          method: "POST",
          body: formData
        });

        if (!uploadRes.ok) throw new Error("Image upload failed");
        const uploadData = await uploadRes.json();
        uploadedFilename = uploadData.filename;
      }

      // Step 2: Submit the job with the correct model and filename
      const generateRes = await fetch("/api/portfolio/imagegen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            model_name: workflow,
            query: query,
            image_filename: uploadedFilename
        })
      });

      const generateData = await generateRes.json();
      if (!generateRes.ok) throw new Error(generateData.detail || "Failed to start");

      const jobId = generateData.job_id;

      // Step B: Poll for status every 2 seconds
      const poll = setInterval(async () => {
        const statusRes = await fetch(`/api/portfolio/status/${jobId}`);
        const statusData = await statusRes.json();

        if (statusData.status === "completed") {
          clearInterval(poll);
          // Append a timestamp so the browser doesn't load a cached image
          setImageUrl(`${statusData.download_url}?t=${new Date().getTime()}`);
          setStatus("completed");
          fetchHistory();
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

  // --- UI ---
  return (
    // Deep, ambient background with a subtle radial gradient
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-[#0f172a] to-black text-slate-200 font-sans selection:bg-cyan-500/30">

      {/* Mobile-friendly container with padding */}
      <div className="max-w-6xl mx-auto px-4 py-8 md:py-16 flex flex-col items-center">

        {/* Header Section */}
        <header className="mb-10 text-center space-y-4 w-full max-w-2xl">
          <div className="inline-block relative">
            <div className="absolute inset-0 bg-cyan-500 blur-3xl opacity-20 animate-pulse"></div>
            <h1 className="relative text-4xl md:text-6xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-cyan-300 to-emerald-300 tracking-tight">
              Image Studio
            </h1>
          </div>
          <p className="text-sm md:text-base text-slate-400 font-light tracking-wide">
            High-Performance AI Generation • K3s Orchestrated • Running on Consumer Hardware
          </p>
        </header>

        {/* Main Generator Glass Panel */}
        <main className="w-full max-w-2xl relative">
          {/* Subtle glow behind the main panel */}
          <div className="absolute -inset-1 bg-gradient-to-r from-blue-500 to-cyan-400 rounded-[2rem] blur-lg opacity-20"></div>

          <div className="relative bg-slate-900/50 backdrop-blur-xl border border-white/10 rounded-3xl shadow-2xl p-6 md:p-8 overflow-hidden">

            {/* Input Section */}
            <div className="flex flex-col gap-4 mb-8">
              <div className="relative group">
                {/* Workflow Selector & Upload */}
                <div className="flex flex-col md:flex-row gap-4 mb-4">
                  <select
                    value={workflow}
                    onChange={(e) => {
                        setWorkflow(e.target.value);
                        setSelectedFile(null); // Clear file if switching modes
                        setWarmedUp(false)
                    }}
                    className="bg-black/40 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-cyan-500/50 flex-1 backdrop-blur-sm appearance-none"
                  >
                    <option value="imagegen">Create an Image</option>
                    <option value="imageedit">Edit an Image</option>
                  </select>

                  {/* Conditional File Upload UI */}
                  {workflow === "imageedit" && (
                    <div className="flex-1 flex items-center">
                      <input
                        type="file"
                        accept="image/png, image/jpeg"
                        className="hidden"
                        ref={fileInputRef}
                        onChange={(e) => setSelectedFile(e.target.files[0])}
                      />
                      <button
                        onClick={() => fileInputRef.current.click()}
                        className={`w-full p-3 rounded-xl border border-dashed transition-all ${selectedFile ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200' : 'border-white/20 bg-black/40 text-slate-400 hover:border-cyan-500/50 hover:bg-cyan-500/10'}`}
                      >
                        {selectedFile ? `Ready: ${selectedFile.name}` : '+ Upload an Image'}
                      </button>
                    </div>
                  )}
                </div>
                <textarea
                  className="w-full bg-black/40 border border-white/10 rounded-2xl p-5 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 resize-none transition-all duration-300 backdrop-blur-sm"
                  rows="3"
                  placeholder="Describe your vision in high detail..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onFocus={handleWarmup}
                />
                {/* Decorative corner accent */}
                <div className="absolute top-0 right-0 w-8 h-8 bg-gradient-to-bl from-cyan-500/20 to-transparent rounded-tr-2xl pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"></div>
              </div>

              <button
                onClick={handleGenerate}
                disabled={status === "processing" || !query.trim()}
                className="group relative w-full overflow-hidden rounded-2xl p-[2px] focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-slate-900 transition-all active:scale-[0.98] disabled:opacity-70 disabled:active:scale-100"
              >
                <span className="absolute inset-0 bg-gradient-to-r from-blue-600 via-cyan-500 to-emerald-400 opacity-80 group-hover:opacity-100 transition-opacity duration-300"></span>
                <div className="relative bg-black/20 backdrop-blur-md px-8 py-4 rounded-[14px] flex items-center justify-center gap-2">
                  <span className="font-bold text-white tracking-wide">
                    {status === "processing" ? "Gathering paint..." : "Create your vision"}
                  </span>
                  {/* Small animated spark/arrow icon */}
                  {status !== "processing" && (
                     <svg className="w-5 h-5 text-cyan-200 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                  )}
                </div>
              </button>
            </div>

            {/* Dynamic Image Display Area */}
            <div className="relative bg-black/60 rounded-2xl min-h-[300px] md:min-h-[450px] flex items-center justify-center border border-white/5 overflow-hidden group transition-all duration-500">

              {status === "idle" && (workflow === "imageedit" && selectedFile ? (
                /* NEW: Show the uploaded reference image immediately while idle */
                <div className="relative w-full h-full flex flex-col items-center justify-center p-4 animate-fade-in">
                  <img
                    src={URL.createObjectURL(selectedFile)}
                    alt="Uploaded reference preview"
                    className="max-h-[260px] md:max-h-[380px] rounded-xl object-contain border border-white/10 shadow-lg"
                  />
                  <p className="text-xs text-slate-400 mt-3 font-light tracking-wide bg-black/40 px-3 py-1 rounded-full border border-white/5">
                    Reference Image Staged
                  </p>
                </div>
              ) : (
                /* Default empty state */
                <div className="text-center text-slate-500 p-8">
                  <svg className="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                  <p className="font-light tracking-wide">C'mon create something cool</p>
                </div>
              )
            )}

              {status === "processing" && (
                <div className="flex flex-col items-center">
                  {/* Custom animated scanner effect */}
                  <div className="relative w-20 h-20 mb-6">
                    <div className="absolute inset-0 border-t-2 border-cyan-400 rounded-full animate-spin"></div>
                    <div className="absolute inset-2 border-r-2 border-blue-500 rounded-full animate-spin border-dashed opacity-70" style={{ animationDirection: 'reverse', animationDuration: '1.5s' }}></div>
                  </div>
                  <p className="text-cyan-400 font-medium animate-pulse tracking-wide text-sm md:text-base">Creating your image...</p>
                </div>
              )}

              {status === "completed" && imageUrl && (
                <img
                  src={imageUrl}
                  alt="Generated output"
                  className="w-full h-full object-cover transition-transform duration-700 hover:scale-105"
                />
              )}

              {status === "error" && (
                <div className="text-red-400 flex items-center gap-2 bg-red-400/10 px-6 py-3 rounded-full border border-red-400/20">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <span className="font-medium tracking-wide">Pipeline Failure</span>
                </div>
              )}
            </div>
          </div>
        </main>

        {/* Database History Gallery */}
        <section className="w-full mt-24 mb-10">
          <div className="flex items-center justify-between mb-8 pb-4 border-b border-white/10">
            <h2 className="text-2xl md:text-3xl font-bold text-white tracking-tight">
              Output <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">Gallery</span>
            </h2>
            <span className="text-xs md:text-sm font-medium text-slate-500 bg-white/5 px-3 py-1 rounded-full border border-white/5">
              {history.length} Records
            </span>
          </div>

          {history.length === 0 ? (
            <div className="bg-white/5 border border-white/5 rounded-2xl py-16 text-center backdrop-blur-sm">
              <p className="text-slate-500 font-light tracking-wide">No persistent records detected in PostgreSQL.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 md:gap-8">
              {history.map((job) => (
                <div
                  key={job.job_id}
                  className="group relative bg-slate-900/40 backdrop-blur-md rounded-2xl overflow-hidden border border-white/10 shadow-xl hover:border-cyan-500/50 transition-all duration-300 hover:-translate-y-1 flex flex-col"
                >
                  <div className="relative aspect-square overflow-hidden bg-black/50">
                    <img
                      src={job.image_url}
                      alt={job.query}
                      className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110 opacity-90 group-hover:opacity-100"
                      loading="lazy"
                    />
                    {/* Hover gradient overlay */}
                    <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
                  </div>

                  <div className="p-5 flex flex-col flex-grow relative z-10 bg-slate-900/80">
                    <p className="text-sm text-slate-300 line-clamp-3 mb-4 flex-grow font-light leading-relaxed" title={job.query}>
                      "{job.query}"
                    </p>
                    <div className="flex justify-between items-center text-[10px] md:text-xs text-slate-500 pt-3 border-t border-white/10 font-mono tracking-wider">
                      <span className="bg-black/30 px-2 py-1 rounded-md">ID: {job.job_id.substring(0,6)}</span>
                      <span>{new Date(job.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

      </div>
    </div>
  );
}

export default App;