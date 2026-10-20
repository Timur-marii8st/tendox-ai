"use client";

import { useEffect, useState, useTransition } from "react";
import { createCharacteristicReadSession, type CharacteristicPairRequest, type CharacteristicReadState } from "../../lib/eis-characteristics";
import { CharacteristicPairReportView } from "./characteristic-pair-report";

export type CharacteristicLoader = (request: CharacteristicPairRequest) => Promise<CharacteristicReadState>;
export function CharacteristicPairPanel({ request, load }: { request: CharacteristicPairRequest; load: CharacteristicLoader }) {
  const [state, setState] = useState<CharacteristicReadState>({});
  const [session] = useState(createCharacteristicReadSession);
  const [pending, startReading] = useTransition();
  useEffect(() => () => session.invalidate(), [session]);
  return <div className="mt-3">
    <button type="button" disabled={pending} className="rounded bg-indigo-700 px-3 py-2 font-bold text-white disabled:opacity-50"
      onClick={() => { setState({}); startReading(async () => {
        const result = await session.read(request, load);
        if (result) setState(result);
      }); }}>{pending ? "Сравниваю характеристики…" : "Сравнить записанные характеристики"}</button>
    {state.error && <p className="mt-2 font-bold text-red-800" role="alert">{state.error}</p>}
    {state.result && <CharacteristicPairReportView report={state.result} />}
  </div>;
}
