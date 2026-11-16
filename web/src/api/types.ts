/** Short names for the generated API types. Never declare API shapes by hand: regenerate schema.d.ts. */
import type { Readable } from "openapi-typescript-helpers"; // openapi-fetch's own helper types
import type { components, operations } from "./schema";

/** As openapi-fetch returns them (`Readable` turns the schema's tuples into arrays). */
type Schemas = { [K in keyof components["schemas"]]: Readable<components["schemas"][K]> };

export type ApiKeyInfo = Schemas["ApiKeyInfo"];
export type ApiKeyCreated = Schemas["ApiKeyCreated"];
export type ChatMessage = Schemas["ChatMessage"];
export type ChatResponse = Schemas["ChatResponse"];
export type Check = Schemas["Check"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type DocumentType = Schemas["DocumentType"];
export type Flag = Schemas["Flag"];
export type FlagCode = Flag["code"];
export type FieldKind = Check["kind"];
export type FormDetail = Schemas["FormDetail"];
export type FormSummary = Schemas["FormSummary"];
export type LibraryDocument = Schemas["LibraryDocument"];
export type LibraryStats = Schemas["LibraryStats"];
export type ReviewRequest = Schemas["ReviewRequest"];
export type Decision = ReviewRequest["decision"];
export type ReviewStatus = NonNullable<LibraryDocument["review_status"]>;
export type SearchFilters = Schemas["SearchFilters"];
export type Source = Schemas["Source"];
export type ValueSource = Schemas["ValueSource"];
export type Scalar = Check["value"];

// Business workspace (business/schema.py)
export type Approval = Schemas["Approval"];
export type ApprovalStatus = Approval["status"];
export type AreaProgress = Schemas["AreaProgress"];
export type AssistantContext = Schemas["AssistantContext"];
export type AssistantInfo = Schemas["AssistantInfo"];
export type AssistantSpec = Schemas["AssistantSpec"];
export type AssistantStatus = AssistantInfo["status"];
export type BusinessProfile = Schemas["BusinessProfile"];
export type ConnectorCreate = Schemas["ConnectorCreate"];
export type ConnectorInfo = Schemas["ConnectorInfo"];
export type ConnectorListing = Schemas["ConnectorListing"];
export type ConnectorStatus = ConnectorInfo["status"];
export type ConnectorTool = Schemas["ConnectorTool"];
export type Hint = Schemas["Hint"];
export type HintsRequest = Schemas["HintsRequest"];
export type InterviewState = Schemas["InterviewState"];
export type Note = Schemas["Note"];
export type OrganizedDocument = Schemas["OrganizedDocument"];
export type OrganizeRequest = Schemas["OrganizeRequest"];
export type PartnerResponse = Schemas["PartnerResponse"];
export type Question = Schemas["Question"];
export type RunResponse = Schemas["RunResponse"];
export type ToolRun = Schemas["ToolRun"];
export type UiEvent = Schemas["UiEvent"];
export type UiState = Schemas["UiState"];
export type WorkspaceSummary = Schemas["WorkspaceSummary"];
export type WriteMode = NonNullable<Schemas["WritePolicy"]["default"]>;

// Knowledge index and workspace databases
export type KnowledgeMap = Schemas["KnowledgeMap"];
export type KnowledgeSource = Schemas["KnowledgeSource"];
export type KnowledgeSearchResponse = Schemas["KnowledgeSearchResponse"];
export type Passage = Schemas["Passage"];
export type SearchHit = Schemas["SearchHit"];
export type Column = Schemas["Column"];
export type ColumnType = NonNullable<Column["type"]>;
export type TableCreate = Schemas["TableCreate"];
export type TableInfo = Schemas["TableInfo"];
export type RowPage = Schemas["RowPage"];
export type QueryResult = Schemas["QueryResult"];
export type CellValue = RowPage["rows"][number][number];

/** Query parameters shared by the document list and stats routes. */
export type DocumentFilters = NonNullable<operations["stats_v1_library_stats_get"]["parameters"]["query"]>;
