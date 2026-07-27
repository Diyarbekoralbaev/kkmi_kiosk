using System.Text.Json.Serialization;
using Kiosk.App.Identity;
using Kiosk.App.Settings;

namespace Kiosk.App.Net;

/// <summary>
/// System.Text.Json source-generated context for every DTO the kiosk
/// (de)serializes. Required for Native AOT — without source generation,
/// JsonSerializer falls back to runtime reflection which is trim-stripped
/// in the AOT publish and would throw at runtime.
///
/// Code-gen happens at compile time. Each [JsonSerializable] annotation
/// tells the generator to emit a typed serializer/deserializer pair, which
/// we then reach via KioskJsonContext.Default.{TypeName}.
///
/// Casing: <see cref="JsonSourceGenerationOptionsAttribute"/>.PropertyNamingPolicy
/// stays at the default (preserve member name) because all our DTOs already
/// pin per-property snake_case via [JsonPropertyName] to match the backend.
/// </summary>
// WhenWritingNull: AppealRequest.Topic is optional — the touch form omits it
// and lets the backend derive a subject from the text. Non-nullable string DTOs
// are unaffected (never null).
[JsonSourceGenerationOptions(DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull)]
[JsonSerializable(typeof(EnrollRequest))]
[JsonSerializable(typeof(EnrollResponse))]
[JsonSerializable(typeof(AuthChallengeResponse))]
[JsonSerializable(typeof(NavigateMessage))]
[JsonSerializable(typeof(TranscriptMessage))]
[JsonSerializable(typeof(MurojatPreviewMessage))]
[JsonSerializable(typeof(MurojatSubmittedMessage))]
[JsonSerializable(typeof(ScheduleMessage))]
[JsonSerializable(typeof(GroupChoicesMessage))]
[JsonSerializable(typeof(DirectionsMessage))]
[JsonSerializable(typeof(DirectionMessage))]
[JsonSerializable(typeof(LeadershipMessage))]
[JsonSerializable(typeof(ReceptionPreviewMessage))]
[JsonSerializable(typeof(ReceptionSubmittedMessage))]
[JsonSerializable(typeof(InfoCardMessage))]
[JsonSerializable(typeof(ServerErrorMessage))]
[JsonSerializable(typeof(ApiError))]
[JsonSerializable(typeof(HeartbeatResponse))]
[JsonSerializable(typeof(KioskSettings))]
[JsonSerializable(typeof(DeviceCredentials))]
[JsonSerializable(typeof(AppealRequest))]
[JsonSerializable(typeof(AppealResponse))]
[JsonSerializable(typeof(FacultyListResponse))]
[JsonSerializable(typeof(GroupListResponse))]
[JsonSerializable(typeof(LessonListResponse))]
[JsonSerializable(typeof(DirectionListResponse))]
[JsonSerializable(typeof(ReceptionRequest))]
[JsonSerializable(typeof(ReceptionResponse))]
// /api/kiosk/officials returns a bare array, so the List<> itself needs a
// generated serializer — the element type alone is not enough.
[JsonSerializable(typeof(System.Collections.Generic.List<OfficialDto>), TypeInfoPropertyName = "ListOfficialDto")]
[JsonSerializable(typeof(CrashLogRequest))]
// Org name translations land as a nested dictionary inside multiple DTOs
// (EnrollResponse, HeartbeatResponse, DeviceCredentials). Registering the
// concrete type once here gives the source generator an explicit hook so the
// AOT build doesn't fall back to reflection.
[JsonSerializable(typeof(System.Collections.Generic.Dictionary<string, string>))]
internal partial class KioskJsonContext : JsonSerializerContext
{
}
