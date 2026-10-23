import { useEffect, useState } from "react";
import { disableGuestLink, fetchGuestLinkStatus, generateGuestLink, revealGuestLink } from "../api";

export default function GuestSharingPage() {
  const [enabled, setEnabled] = useState(false);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchGuestLinkStatus().then((status) => setEnabled(status.enabled))
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  }, []);

  async function showLink() {
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const result = await revealGuestLink();
      setLink(`${window.location.origin}/#guest=${result.token}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not retrieve guest link");
    } finally {
      setBusy(false);
    }
  }

  async function changeLink(disable: boolean) {
    if (enabled && !window.confirm(disable
      ? "Disable guest access? The link and all existing guest sessions will stop working."
      : "Regenerate the link? The old link and all existing guest sessions will stop working.")) return;
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      if (disable) {
        await disableGuestLink();
        setEnabled(false);
        setLink("");
      } else {
        const result = await generateGuestLink();
        setLink(`${window.location.origin}/#guest=${result.token}`);
        setEnabled(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update guest access");
    } finally {
      setBusy(false);
    }
  }

  const localOnly = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-4xl text-stone-100">Guest access</h1>
        <p className="mt-3 text-stone-400">Share one private link with your friends. They can browse your collection, decks, and deck cards without an account. Editing and AI tools stay private.</p>
      </div>
      <div className="space-y-5 rounded-2xl border border-white/10 bg-ink-900/40 p-6">
        <p className="text-stone-200">{busy ? "Checking guest access…" : enabled ? "Guest access is enabled" : "Guest access is disabled"}</p>
        <p className="text-sm text-stone-400">Anyone with the link can view your collection and decks. Regenerating or disabling it immediately revokes the old link and every guest session.</p>
        <div className="flex flex-wrap gap-3">
          {enabled && <button disabled={busy} onClick={() => void showLink()} className="rounded-xl bg-arcane-500/20 px-4 py-3 text-arcane-100 ring-1 ring-arcane-400/30 disabled:opacity-40">Show existing guest link</button>}
          <button disabled={busy} onClick={() => void changeLink(false)} className="rounded-xl bg-ember-500/20 px-4 py-3 text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40">{enabled ? "Regenerate guest link" : "Generate guest link"}</button>
          {enabled && <button disabled={busy} onClick={() => void changeLink(true)} className="rounded-xl border border-white/20 px-4 py-3 text-stone-300 disabled:opacity-40">Disable guest access</button>}
        </div>
        {link && <div className="space-y-3">
          <label className="block text-sm text-stone-300">Private guest link
            <input readOnly value={link} onFocus={(event) => event.target.select()} className="mt-2 w-full rounded-lg border border-white/10 bg-ink-950 p-3 font-mono text-xs text-stone-200" />
          </label>
          <button onClick={() => void navigator.clipboard.writeText(link).then(() => setCopied(true)).catch(() => setError("Select and copy the link above manually."))} className="rounded-lg border border-white/20 px-4 py-2 text-sm text-stone-200">{copied ? "Copied!" : "Copy link"}</button>
        </div>}
        <p className="text-xs text-stone-500">Use “Show existing guest link” to share the same link with another friend. Showing or copying it keeps the link and everyone’s access working.</p>
        {localOnly && <p className="text-sm text-amber-200">This address only works on your Mac. Generate your friends’ link while visiting your hosted site at its public HTTPS address.</p>}
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      </div>
    </section>
  );
}
