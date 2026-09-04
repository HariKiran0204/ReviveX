"use client";

import { use } from "react";
import { CaseDetailScreen } from "./CaseDetailScreen";

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <CaseDetailScreen caseId={id} />;
}
