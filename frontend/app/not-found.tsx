import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="max-w-lg text-center">
        <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-400">404 · Event not found</p>
        <h1 className="mt-4 text-4xl font-semibold text-white">This event is not in the archive.</h1>
        <p className="mt-4 leading-7 text-slate-400">The slug may be invalid, or the event may no longer be available.</p>
        <Link className="mt-7 inline-flex rounded-xl bg-white px-4 py-2.5 text-sm font-bold text-slate-950 outline-none hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-emerald-300" href="/">
          Return to events
        </Link>
      </div>
    </main>
  );
}
