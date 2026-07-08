import { JobProgress } from "@/components/JobProgress";

type JobPageProps = {
  params: Promise<{ jobId: string }>;
};

export default async function JobPage({ params }: JobPageProps) {
  const { jobId } = await params;
  return <JobProgress jobId={jobId} />;
}
