import type { ReactElement } from "react";

type Props = {
  law: "44" | "223";
  offset: number;
  count: number;
  mayHaveMore: boolean;
  disabled: boolean;
  className: string;
  onNext: () => void;
};

export function GosplanPagination({ law, offset, count, mayHaveMore, disabled, className, onNext }: Props): ReactElement | null {
  if (!mayHaveMore) return null;
  if (offset + count > 1000) {
    return <p>Достигнут предел просмотра; уточните запрос. Полнота выдачи не подтверждена.</p>;
  }
  return <button type="button" className={className} disabled={disabled} onClick={onNext}>Следующая страница · {law}-ФЗ</button>;
}
