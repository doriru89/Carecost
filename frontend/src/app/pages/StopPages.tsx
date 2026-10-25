import { Phone, MessageSquare, Globe } from "lucide-react";
import { t } from "@/contracts/copy";
import type { RedFlagReply } from "@/generated/contracts/chat_api";

/**
 * Full-page stops (plan §4.1, v2): no prices, no list, no map. The headline and text are the
 * reply's, which the contract copies verbatim from data/redflags/redflags.json.
 */
export function RedFlagPage({ reply, onBack }: { reply: RedFlagReply; onBack: () => void }) {
  if (reply.disposition === "crisis_988") return <CrisisPage reply={reply} onBack={onBack} />;
  const urgent = reply.disposition === "call_911" || reply.disposition === "er_today";
  return (
    <main
      className={urgent ? "min-h-screen bg-red-700 text-white" : "min-h-screen bg-amber-50 text-foreground"}
      data-testid="red-flag-page"
      data-disposition={reply.disposition}
    >
      <div className="mx-auto max-w-xl px-5 py-14 sm:py-24 space-y-6">
        <h1 className="text-4xl sm:text-5xl font-bold leading-tight">{reply.headline.en}</h1>
        <p className="text-lg leading-relaxed">{reply.text.en}</p>
        {urgent && (
          <a
            href="tel:911"
            className="flex items-center justify-center gap-2 rounded-2xl bg-white px-6 py-4 text-xl font-bold text-red-700 shadow-lg"
          >
            <Phone className="h-6 w-6" /> {t("redflag.call_911")}
          </a>
        )}
        <p className={urgent ? "text-sm text-white/80" : "text-sm text-muted-foreground"}>{t("redflag.no_prices")}</p>
        <button type="button" onClick={onBack} className="text-sm underline opacity-80">
          {t("redflag.back_home")}
        </button>
      </div>
    </main>
  );
}

/** crisis_988 gets its own calm page (rank 4, same as 911). All wording here is pending Austin's review. */
export function CrisisPage({ reply, onBack }: { reply: RedFlagReply; onBack: () => void }) {
  const btn = "flex items-center justify-center gap-2 rounded-2xl px-6 py-4 text-lg font-semibold shadow";
  return (
    <main className="min-h-screen bg-[#20304a] text-white" data-testid="crisis-page" data-disposition="crisis_988">
      <div className="mx-auto max-w-xl px-5 py-14 sm:py-24 space-y-6">
        <h1 className="text-4xl sm:text-5xl font-bold leading-tight">{reply.headline.en}</h1>
        <p className="text-lg leading-relaxed text-white/90">{reply.text.en}</p>
        <p className="text-base text-white/80">{t("crisis.not_alone")}</p>
        <div className="grid gap-3">
          <a href="tel:988" className={`${btn} bg-white text-[#20304a]`}>
            <Phone className="h-5 w-5" /> {t("crisis.call_988")}
          </a>
          <a href="sms:988" className={`${btn} bg-white/15 text-white border border-white/30`}>
            <MessageSquare className="h-5 w-5" /> {t("crisis.text_988")}
          </a>
          <a href="https://988lifeline.org/chat/" target="_blank" rel="noreferrer" className={`${btn} bg-white/15 text-white border border-white/30`}>
            <Globe className="h-5 w-5" /> {t("crisis.chat_988")}
          </a>
        </div>
        <a href="tel:911" className="block text-center text-base font-semibold underline">
          {t("crisis.danger_911")}
        </a>
        <p className="text-sm text-white/70">{t("redflag.no_prices")}</p>
        <button type="button" onClick={onBack} className="text-sm underline text-white/70">
          {t("redflag.back_home")}
        </button>
      </div>
    </main>
  );
}
