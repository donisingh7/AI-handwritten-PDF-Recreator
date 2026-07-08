import { JobProgress } from "@/components/JobProgress";

export default function JobPage({ params }: { params: { jobId: string } }) {
  return <JobProgress jobId={params.jobId} />;
}
