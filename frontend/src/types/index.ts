export type Project = {
  id: string;
  title: string;
  intent: string;
  style: string;
  input_mode: string;
  target_duration_s: number;
  revision: number;
  latest_analysis_id: string | null;
  demo_scenario: string | null;
  created_at: string;
  asset_count?: number;
  duration_s?: number;
  cover_url?: string;
  constraints_json: { primary_asset_id?: string };
};
export type Shot = {
  id: string;
  asset_id: string;
  index: number;
  start_s: number;
  end_s: number;
  thumbnail_url?: string | null;
  boundary_type: string;
  summary?: string;
  evidence_ids?: string[];
  observed?: boolean;
};
export type Asset = {
  id: string;
  original_name: string;
  source_type: string;
  duration_s: number;
  width: number;
  height: number;
  status: string;
  has_audio: boolean;
  audio_status: string;
  preview_url: string | null;
  original_url: string;
  thumbnail_url: string | null;
  synthetic_media: boolean;
  shots?: Shot[];
  shot_count?: number;
  segmentation_version?: string;
};
export type Job = {
  id: string;
  type: string;
  status: string;
  stage: string;
  completed_units: number;
  total_units: number;
  error_message: string | null;
  error_code: string | null;
  retry_count: number;
  asset_id?: string;
  analysis_id?: string;
  edit_id?: string;
  submission_id?: string;
  task_id?: string;
  provider_task_id?: string;
  generation_retryable?: boolean;
  prompt?: string;
  duration_s?: number;
  resolution?: "480P" | "720P" | "1080P";
  reference_asset_id?: string;
  reference_time_s?: number;
};
export type GenerationOptions = {
  available: boolean;
  reason?: string;
  model: string;
  prompt: string;
  duration_s: number;
  resolution: "480P" | "720P" | "1080P";
  reference_frames: NonNullable<Task["reference_frames"]>;
  latest_job?: Job | null;
};
export type Evidence = {
  id: string;
  shot_id?: string;
  asset_id: string;
  source_start_s: number;
  source_end_s: number;
  action: string;
  subjects: string[];
  uncertainty: string;
  quality_issues: string[];
  evidence_type: string;
  provenance: { provider: string; demo?: boolean; dense_review?: boolean };
};
export type Requirement = {
  id: string;
  description: string;
  priority: string;
  origin: string;
  user_confirmed: boolean;
  accepted_evidence_types: string[];
};
export type Gap = {
  id: string;
  requirement_id: string;
  type: string;
  severity: string;
  status: string;
  reason: string;
  description: string;
  evidence_ids: string[];
  uncertain: boolean;
  optional: boolean;
  human_reason?: string;
  anchor?: {
    asset_id: string;
    shot_id: string;
    related_shot_id?: string;
    start_s: number;
    end_s: number;
    insert_at_s: number;
  };
  impact?: string;
  recommendation?: {
    kind: "reshoot" | "reedit";
    instruction: string;
    shot_scale: string;
    subject_action: string;
    duration_s: number;
    insert_position: "before" | "after" | "replace";
    acceptance_checks: string[];
  };
  searched_ranges: { asset_id: string; start_s: number; end_s: number }[];
  alternative_edit: { feasible: boolean; reason: string };
};
export type Analysis = {
  id: string;
  status: string;
  stage: string;
  project_revision: number;
  stale: boolean;
  provider: string;
  coverage?: {
    visual_complete: boolean;
    audio_complete: boolean;
    ranges: {
      asset_id: string;
      start_s: number;
      end_s: number;
      audio_status: string;
    }[];
    failed_ranges: { reason: string }[];
    cached_asset_ids: string[];
    sampling_note: string;
  };
};
export type Diagnosis = {
  shots?: Shot[];
  vlog?: {
    summary: string;
    vlog_type: string;
    chapters: { title: string; shot_ids: string[]; summary: string }[];
    primary_asset_id: string;
    shot_count: number;
  };
  analysis: Analysis;
  requirements: Requirement[];
  evidence: Evidence[];
  gaps: Gap[];
  matches: {
    requirement_id: string;
    evidence_ids: string[];
    sufficiency: string;
    reason: string;
  }[];
};
export type Check = {
  check: string;
  status: string;
  reason: string;
  evidence_ids: string[];
};
export type Submission = {
  id: string;
  asset_id?: string;
  verification_status: string;
  reason?: string;
  checks?: Check[];
  new_evidence?: Evidence[];
  stale?: boolean;
};
export type Task = {
  anchor?: Gap["anchor"];
  recommendation?: Gap["recommendation"];
  id: string;
  type: string;
  instruction: string;
  requirement_description: string;
  acceptance_checks: string[];
  estimated_effort_min: number;
  prompt: string;
  continuity: string;
  selected: boolean;
  needs_confirmation: boolean;
  reference_evidence_ids: string[];
  reference_frames?: {
    asset_id: string;
    time_s: number;
    url: string;
    caption: string;
  }[];
  submissions: Submission[];
};
export type Plan = {
  id: string;
  analysis_id: string;
  tasks: Task[];
  budget_min: number | null;
  estimated_effort_min: number;
  uncovered_gap_ids: string[];
  note: string;
};
export type Clip = {
  asset_id: string;
  source_in_s: number;
  source_out_s: number;
};
export type Edit = {
  id: string;
  created_at: string;
  analysis_id: string;
  render_status: string;
  output_url: string | null;
  edl_url: string;
  duration_s: number;
  timeline: Clip[];
  note: string;
};
export type Health = {
  provider: string;
  model_configured: boolean;
  queue_mode: string;
  ffmpeg_available: boolean;
  asr_configured: boolean;
  model_destination: string | null;
  limits: { max_upload_mb: number; max_assets: number; max_duration_s: number };
};
