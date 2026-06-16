"use client";

import React, { useMemo, useState } from "react";
import styles from "./page.module.css";
import {
  SiArxiv,
  SiGithub,
  SiGithubactions,
  SiYcombinator,
  SiPython,
  SiGoogle,
  SiSlack,
  SiBluesky,
  SiX,
} from "react-icons/si";
import type { IconType } from "react-icons";

type IconDef = { Icon: IconType; color: string };

type Step = {
  id: string;
  icons: IconDef[];
  label: string;
  desc: string;
};

const steps: Step[] = [
  {
    id: "sources",
    icons: [
      { Icon: SiArxiv, color: "#b31b1b" },
      { Icon: SiYcombinator, color: "#ff6600" },
      { Icon: SiGithub, color: "#e7e7e7" },
    ],
    label: "Sources",
    desc: "18 RSS/Atom · HN · Trending",
  },
  {
    id: "ingest",
    icons: [{ Icon: SiPython, color: "#3776ab" }],
    label: "Ingest",
    desc: "Normalize & deduplicate",
  },
  {
    id: "tiers",
    icons: [{ Icon: SiPython, color: "#3776ab" }],
    label: "Reputation",
    desc: "Tier-1/2/3 source weights",
  },
  {
    id: "cluster",
    icons: [{ Icon: SiGithubactions, color: "#2088ff" }],
    label: "Cluster",
    desc: "Cross-source corroboration",
  },
  {
    id: "rank",
    icons: [{ Icon: SiGoogle, color: "#4285f4" }],
    label: "Rank",
    desc: "Story score + LLM pass",
  },
  {
    id: "publish",
    icons: [
      { Icon: SiBluesky, color: "#0285ff" },
      { Icon: SiX, color: "#e7e7e7" },
    ],
    label: "Publish",
    desc: "Bluesky · X",
  },
];

const payloadByStep: Record<string, string> = {
  sources: `[
  {"source":"OpenAI News","title":"Dell + Codex partnership","link":"https://openai.com/index/dell-codex-enterprise-partnership"},
  {"source":"HackerNews","title":"Show HN: local coding agent","points":412,"comments":97}
]`,
  ingest: `{
  "seen_items_before": 1820,
  "new_items_raw": 63,
  "duplicates_removed": 21,
  "items_after_dedupe": 42
}`,
  tiers: `[
  {"source":"OpenAI News","tier":1,"engagement":0.0},
  {"source":"SemiAnalysis","tier":2,"engagement":0.0},
  {"source":"HackerNews","tier":3,"engagement":412.0}
]`,
  cluster: `{
  "cluster_id": "c_017",
  "story_score": 12.84,
  "rep_link": "https://openai.com/index/dell-codex-enterprise-partnership",
  "members": 4
}`,
  rank: `[
  {"id":0,"score":89,"should_post":true,"reason":"multi-source corroboration"},
  {"id":1,"score":76,"should_post":true,"reason":"high builder impact"},
  {"id":2,"score":41,"should_post":false,"reason":"too generic"}
]`,
  publish: `{
  "platform": "bluesky",
  "status": "queued_or_posted",
  "card_path": "generated/cards/ab12cd34ef56.png",
  "source_link": "https://openai.com/index/dell-codex-enterprise-partnership"
}`,
};

function StepCard({
  step,
  active,
  onActivate,
}: {
  step: Step;
  active: boolean;
  onActivate: () => void;
}) {
  return (
    <button
      type="button"
      className={`${styles.flowStep} ${active ? styles.flowStepActive : ""}`}
      onMouseEnter={onActivate}
      onFocus={onActivate}
      onClick={onActivate}
      aria-label={`Show details for ${step.label}`}
    >
      <div className={styles.flowIcons}>
        {step.icons.map(({ Icon, color }, j) => (
          <Icon key={j} size={step.icons.length === 1 ? 32 : 22} color={color} aria-hidden />
        ))}
      </div>
      <span className={styles.flowStepLabel}>{step.label}</span>
      <span className={styles.flowStepDesc}>{step.desc}</span>
    </button>
  );
}

export default function Workflow() {
  const [activeId, setActiveId] = useState<string>("rank");
  const active = useMemo(
    () => steps.find((step) => step.id === activeId) ?? steps[0],
    [activeId],
  );

  return (
    <div className={styles.flowWrap}>
      <div className={styles.flowGrid}>
        <div className={styles.flowDesktopRow}>
          {steps.map((step, i) => (
            <React.Fragment key={`desktop-${step.id}`}>
              <StepCard
                step={step}
                active={activeId === step.id}
                onActivate={() => setActiveId(step.id)}
              />
              {i < steps.length - 1 && <div className={styles.flowArrowH} />}
            </React.Fragment>
          ))}
        </div>

        <div className={styles.flowMobileRows}>
          <div className={styles.flowMobileRow}>
            {steps.slice(0, 3).map((step, i) => (
              <React.Fragment key={`m1-${step.id}`}>
                <StepCard
                  step={step}
                  active={activeId === step.id}
                  onActivate={() => setActiveId(step.id)}
                />
                {i < 2 && <div className={styles.flowArrowH} />}
              </React.Fragment>
            ))}
          </div>
          <div className={styles.flowMobileRow}>
            {steps.slice(3).map((step, i) => (
              <React.Fragment key={`m2-${step.id}`}>
                <StepCard
                  step={step}
                  active={activeId === step.id}
                  onActivate={() => setActiveId(step.id)}
                />
                {i < 2 && <div className={styles.flowArrowH} />}
              </React.Fragment>
            ))}
          </div>
        </div>

        <div className={styles.flowBranchRank}>
          <div className={styles.flowArrowV} />
        </div>

        <div className={styles.flowSlackOnly}>
          <div className={styles.sideItemPrimary}>
            <SiSlack size={30} color="#e01e5a" aria-hidden />
            <span className={styles.sideItemLabel}>Slack</span>
            <span className={styles.sideItemDesc}>Agent communication bus</span>
          </div>
        </div>

        <div className={styles.flowPreview}>
          <div className={styles.flowPreviewTop}>
            <p className={styles.flowDetailLabel}>LIVE PAYLOAD PREVIEW</p>
            <span className={styles.flowPreviewStep}>{active.label}</span>
          </div>
          <pre className={styles.flowPreviewCode}>{payloadByStep[active.id]}</pre>
        </div>
      </div>

      <div className={styles.flowLegend}>
        <span>
          <span className={styles.flowLegendDot} aria-hidden />
          hover or tap a step for payload samples
        </span>
        <span>core pipeline + rank-to-slack agent coordination</span>
      </div>
    </div>
  );
}
