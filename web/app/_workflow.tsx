import React from "react";
import styles from "./page.module.css";
import {
  SiArxiv,
  SiGithub,
  SiGithubactions,
  SiYcombinator,
  SiPython,
  SiGoogle,
  SiBluesky,
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
    icons: [{ Icon: SiBluesky, color: "#0285ff" }],
    label: "Publish",
    desc: "Bluesky",
  },
];

function StepCard({
  step,
}: {
  step: Step;
}) {
  return (
    <div className={styles.flowStep}>
      <div className={styles.flowIcons}>
        {step.icons.map(({ Icon, color }, j) => (
          <Icon key={j} size={step.icons.length === 1 ? 32 : 22} color={color} aria-hidden />
        ))}
      </div>
      <span className={styles.flowStepLabel}>{step.label}</span>
      <span className={styles.flowStepDesc}>{step.desc}</span>
    </div>
  );
}

export default function Workflow() {
  return (
    <div className={styles.flowWrap}>
      <div className={styles.flowGrid}>
        <div className={styles.flowDesktopRow}>
          {steps.map((step, i) => (
            <React.Fragment key={`desktop-${step.id}`}>
              <StepCard step={step} />
              {i < steps.length - 1 && <div className={styles.flowArrowH} />}
            </React.Fragment>
          ))}
        </div>

        <div className={styles.flowMobileRows}>
          <div className={styles.flowMobileRow}>
            {steps.slice(0, 3).map((step, i) => (
              <React.Fragment key={`m1-${step.id}`}>
                <StepCard step={step} />
                {i < 2 && <div className={styles.flowArrowH} />}
              </React.Fragment>
            ))}
          </div>
          <div className={styles.flowMobileRow}>
            {steps.slice(3).map((step, i) => (
              <React.Fragment key={`m2-${step.id}`}>
                <StepCard step={step} />
                {i < 2 && <div className={styles.flowArrowH} />}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
