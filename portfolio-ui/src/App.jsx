import { useState } from 'react';

function App() {
  return (
    // We are using Tailwind CSS classes here directly in the className
    <div className="min-h-screen bg-slate-900 text-white flex flex-col items-center p-10">

      <header className="mb-12 text-center">
        <h1 className="text-4xl font-bold text-blue-400 mb-4">
          Z-Turbo Image Generator
        </h1>
        <p className="text-slate-400">
          Powered by FastAPI & ComfyUI
        </p>
      </header>

      <main className="w-full max-w-2xl bg-slate-800 rounded-xl shadow-lg p-8">
        <p className="text-center text-slate-300">
          Our frontend UI will go here. Tailwind is working perfectly!
        </p>
      </main>

    </div>
  );
}

export default App;