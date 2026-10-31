import type { Metadata } from "next";
import Link from "next/link";

import { TenderDiscoveryForm } from "./form";
import { MixedComparisonProvider } from "./mixed-comparison";
import { IndexedSearch } from "./indexed-search";
import { Indexed223Search } from "./indexed-223-search";
import { TenderDiscoveryWorkflow } from "./workflow";
import { loadEis223RegionalCoverage } from "./actions";
import { RegionalCoverage } from "./regional-coverage";
import { loadNoticeProfileContext } from "./profile-comparison-actions";
import { TenderWorkspace } from "./workspace";
import { GosplanWorkspace } from "./gosplan-workspace";
import styles from "./workspace.module.css";

export const metadata: Metadata = { title: "Поиск закупок ЕИС — Tendox" };
export const dynamic = "force-dynamic";

export default async function TenderDiscoveryPage() {
  const [regionalCoverage, profile] = await Promise.all([loadEis223RegionalCoverage(), loadNoticeProfileContext()]);
  return <main className={styles.page}>
    <div className={styles.shell}>
      <nav aria-label="Разделы закупок" className={styles.nav}>
        <Link href="/" className={styles.brand} aria-label="Tendox — дела"><span className={styles.brandMark} aria-hidden="true">T</span>Tendox</Link>
        <div className={styles.navLinks}>
          <Link href="/tender-discovery" aria-current="page" className={styles.navActive}>Поиск закупок</Link>
          <Link href="/">Мои дела</Link>
          <Link href="/procurement-comparison">Сравнение кейсов</Link>
          <Link href="/company-profile" className={styles.profileLink}>Профиль компании ↗</Link>
        </div>
      </nav>
      <div className={styles.content}>
        <MixedComparisonProvider profileContext={profile.context} profileError={profile.error}>
          <GosplanWorkspace />
          <details className={styles.advanced}>
            <summary>Поиск в нашей базе и расширенные инструменты</summary>
            <div className={styles.legacyContent}>
              <TenderWorkspace />
              <IndexedSearch />
              <Indexed223Search />
              <details className={styles.legacySection}>
                <summary>Состояние загрузки каталога · 223-ФЗ</summary>
                <RegionalCoverage initial={regionalCoverage} />
              </details>
              <details className={styles.legacySection}>
                <summary>Поиск по публичной выдаче ЕИС</summary>
                <TenderDiscoveryWorkflow />
              </details>
              <details className={styles.legacySection}>
                <summary>Разовый поиск и XML/ZIP-выгрузка</summary>
                <p>Резервный режим для одной страницы ЕИС или заранее сохранённой выгрузки без сессии.</p>
                <TenderDiscoveryForm />
              </details>
            </div>
          </details>
        </MixedComparisonProvider>
      </div>
    </div>
  </main>;
}
