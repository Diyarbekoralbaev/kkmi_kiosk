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
[JsonSerializable(typeof(EnrollRequest))]
[JsonSerializable(typeof(EnrollResponse))]
[JsonSerializable(typeof(AuthChallengeResponse))]
[JsonSerializable(typeof(NavigateMessage))]
[JsonSerializable(typeof(TranscriptMessage))]
[JsonSerializable(typeof(ApplicationPreviewMessage))]
[JsonSerializable(typeof(ApplicationSubmittedMessage))]
[JsonSerializable(typeof(AppointmentProgressMessage))]
[JsonSerializable(typeof(AppointmentPreviewMessage))]
[JsonSerializable(typeof(AppointmentSubmittedMessage))]
[JsonSerializable(typeof(FeedbackPreviewMessage))]
[JsonSerializable(typeof(FeedbackSubmittedMessage))]
[JsonSerializable(typeof(ServerErrorMessage))]
[JsonSerializable(typeof(ApiError))]
[JsonSerializable(typeof(HeartbeatResponse))]
[JsonSerializable(typeof(KioskSettings))]
[JsonSerializable(typeof(DeviceCredentials))]
[JsonSerializable(typeof(CreateAppointmentRequest))]
[JsonSerializable(typeof(CreateAppointmentResponse))]
[JsonSerializable(typeof(CreateApplicationRequest))]
[JsonSerializable(typeof(CreateApplicationResponse))]
[JsonSerializable(typeof(CreateFeedbackRequest))]
[JsonSerializable(typeof(CreateFeedbackResponse))]
// Org name translations land as a nested dictionary inside multiple DTOs
// (EnrollResponse, HeartbeatResponse, AppointmentSubmittedMessage,
// CreateAppointmentResponse, DeviceCredentials). Registering the concrete
// type once here gives the source generator an explicit hook so the AOT
// build doesn't need to fall back to reflection for it.
[JsonSerializable(typeof(System.Collections.Generic.Dictionary<string, string>))]
internal partial class KioskJsonContext : JsonSerializerContext
{
}
