import styles from "./Badge.module.css";

type Tone = "default" | "accent" | "success" | "warning" | "danger" | "muted";

export default function Badge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
