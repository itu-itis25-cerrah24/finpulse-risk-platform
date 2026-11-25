import { ExternalLink } from "lucide-react";

import type { Headline, Sentiment, SentimentLabel } from "../../api/types";
import { formatRelativeTime } from "../../lib/format";
import { SentimentBadge } from "../ui/Badges";

const accent: Record<SentimentLabel, string> = {
  BULLISH: "bg-emerald-500",
  BEARISH: "bg-rose-500",
  NEUTRAL: "bg-zinc-600",
};

interface NewsFeedProps {
  headlines: Headline[];
  sentiment: Sentiment;
}

export function NewsFeed({ headlines, sentiment }: NewsFeedProps) {
  return (
    <section className="panel flex min-h-0 flex-col">
      <header className="panel-header">
        <h3 className="panel-title">News Sentiment</h3>
        <div className="flex items-center gap-2">
          <span className="num text-[11px] text-zinc-500">
            avg {sentiment.score >= 0 ? "+" : ""}
            {sentiment.score.toFixed(3)}
          </span>
          <SentimentBadge label={sentiment.label} />
        </div>
      </header>

      {headlines.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-4 py-10 text-sm text-zinc-500">
          No recent headlines for this symbol.
        </div>
      ) : (
        <ul className="max-h-[320px] flex-1 divide-y divide-zinc-800/70 overflow-y-auto">
          {headlines.map((h, index) => (
            <li key={`${h.title}-${index}`} className="group flex gap-3 px-4 py-2.5">
              <span
                className={`mt-1 h-8 w-0.5 shrink-0 rounded-full ${accent[h.sentiment_label]}`}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                {h.link ? (
                  <a
                    href={h.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="line-clamp-2 text-[13px] leading-snug text-zinc-200 transition group-hover:text-white hover:underline"
                  >
                    {h.title}
                    <ExternalLink className="ml-1 inline h-3 w-3 text-zinc-600" />
                  </a>
                ) : (
                  <p className="line-clamp-2 text-[13px] leading-snug text-zinc-200">{h.title}</p>
                )}
                <div className="mt-1 flex items-center gap-2 text-[11px] text-zinc-500">
                  <span className="truncate">{h.publisher ?? "Unknown source"}</span>
                  {h.published_at && (
                    <>
                      <span className="text-zinc-700">·</span>
                      <span className="shrink-0">{formatRelativeTime(h.published_at)}</span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <SentimentBadge label={h.sentiment_label} />
                <span className="num text-[10px] text-zinc-500">
                  {h.sentiment_score >= 0 ? "+" : ""}
                  {h.sentiment_score.toFixed(2)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
