import ReferralClient from "./ReferralClient";

export const dynamic = "force-dynamic";

export default function ReferralPage({ params }: { params: { code: string } }) {
  const code = (params.code || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12) || "WX000000";
  return <ReferralClient code={code} />;
}
