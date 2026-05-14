import { NavLink, Outlet } from "react-router-dom";
import styles from "./Layout.module.css";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/ask", label: "Ask", end: false },
  { to: "/documents", label: "Documents", end: false },
  { to: "/entities", label: "Entities", end: false },
  { to: "/ingest", label: "Ingest", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export default function Layout() {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>Personal RAG</div>
        <nav className={styles.nav}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
