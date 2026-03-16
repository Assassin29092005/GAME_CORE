#include "RLBridgeComponent.h"
#include "Networking.h"
#include "StateObservationComponent.h"
#include "PlayerMemoryComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

URLBridgeComponent::URLBridgeComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void URLBridgeComponent::BeginPlay()
{
	Super::BeginPlay();

	if (bAutoStart)
	{
		StartServer();
	}
}

void URLBridgeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	StopServer();
	Super::EndPlay(EndPlayReason);
}

void URLBridgeComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	// Pick up pending connection from listener thread (thread-safe handoff)
	{
		FScopeLock Lock(&PendingSocketMutex);
		if (PendingClientSocket)
		{
			if (ClientSocket)
			{
				ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
			}
			ClientSocket = PendingClientSocket;
			PendingClientSocket = nullptr;
			ReceiveBuffer.Empty();
			UE_LOG(LogTemp, Log, TEXT("RLBridge: Client connection established"));
		}
	}

	if (!ClientSocket) return;

	// Throttle processing to configured tick rate
	TickAccumulator += DeltaTime;
	const float TickInterval = 1.0f / FMath::Max(TickRate, 1);

	if (TickAccumulator >= TickInterval)
	{
		TickAccumulator -= TickInterval;
		ProcessIncomingData();
	}
}

void URLBridgeComponent::StartServer()
{
	if (TcpListener) return;

	FIPv4Endpoint Endpoint(FIPv4Address::Any, ListenPort);

	TcpListener = new FTcpListener(Endpoint, FTimespan::FromSeconds(1.0f));
	TcpListener->OnConnectionAccepted().BindUObject(this, &URLBridgeComponent::OnConnectionAccepted);

	if (TcpListener->Init())
	{
		UE_LOG(LogTemp, Log, TEXT("RLBridge: TCP server listening on port %d"), ListenPort);
	}
	else
	{
		UE_LOG(LogTemp, Error, TEXT("RLBridge: Failed to start TCP server on port %d"), ListenPort);
		delete TcpListener;
		TcpListener = nullptr;
	}
}

void URLBridgeComponent::StopServer()
{
	CleanupSockets();
}

bool URLBridgeComponent::OnConnectionAccepted(FSocket* InSocket, const FIPv4Endpoint& Endpoint)
{
	// Called from listener thread — only touch PendingClientSocket (mutex-protected)
	FScopeLock Lock(&PendingSocketMutex);

	if (PendingClientSocket)
	{
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(InSocket);
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: Rejected connection, one already pending"));
		return false;
	}

	PendingClientSocket = InSocket;
	UE_LOG(LogTemp, Log, TEXT("RLBridge: Python client connecting from %s"), *Endpoint.ToString());
	return true;
}

void URLBridgeComponent::ProcessIncomingData()
{
	if (!ClientSocket) return;

	uint32 PendingDataSize = 0;
	if (!ClientSocket->HasPendingData(PendingDataSize) || PendingDataSize == 0) return;

	TArray<uint8> Buffer;
	Buffer.SetNumZeroed(PendingDataSize + 1); // +1 for null terminator

	int32 BytesRead = 0;
	if (!ClientSocket->Recv(Buffer.GetData(), PendingDataSize, BytesRead))
	{
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: Client disconnected"));
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
		ClientSocket = nullptr;
		ReceiveBuffer.Empty();
		return;
	}

	if (BytesRead <= 0) return;

	// Null-terminate at actual bytes read
	Buffer[BytesRead] = 0;

	// Append to persistent receive buffer
	ReceiveBuffer += UTF8_TO_TCHAR(reinterpret_cast<const char*>(Buffer.GetData()));

	// Process complete newline-delimited messages
	int32 NewlineIdx = INDEX_NONE;
	while (ReceiveBuffer.FindChar(TEXT('\n'), NewlineIdx))
	{
		FString Line = ReceiveBuffer.Left(NewlineIdx).TrimStartAndEnd();
		ReceiveBuffer.MidInline(NewlineIdx + 1);

		if (!Line.IsEmpty())
		{
			ProcessMessage(Line);
		}
	}
}

void URLBridgeComponent::ProcessMessage(const FString& Message)
{
	TSharedPtr<FJsonObject> JsonObject;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);

	if (!FJsonSerializer::Deserialize(Reader, JsonObject) || !JsonObject.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: Failed to parse JSON: %s"), *Message);
		return;
	}

	// Handle action messages: {"action": N}
	if (JsonObject->HasField(TEXT("action")))
	{
		const int32 ActionIndex = JsonObject->GetIntegerField(TEXT("action"));
		OnRLActionReceived.Broadcast(ActionIndex);
		return;
	}

	// Handle command messages: {"command": "reset"} or {"command": "observe"}
	if (JsonObject->HasField(TEXT("command")))
	{
		const FString Command = JsonObject->GetStringField(TEXT("command"));

		if (Command == TEXT("reset"))
		{
			OnRLResetRequested.Broadcast();
			HandleObserveRequest();
		}
		else if (Command == TEXT("observe"))
		{
			HandleObserveRequest();
		}
		else if (Command == TEXT("get_profile"))
		{
			HandleGetProfileRequest();
		}
		else if (Command == TEXT("set_player_id"))
		{
			const FString PlayerId = JsonObject->GetStringField(TEXT("player_id"));
			HandleSetPlayerId(PlayerId);
		}
		else
		{
			UE_LOG(LogTemp, Warning, TEXT("RLBridge: Unknown command: %s"), *Command);
		}
		return;
	}

	UE_LOG(LogTemp, Warning, TEXT("RLBridge: Unrecognized message: %s"), *Message);
}

void URLBridgeComponent::HandleObserveRequest()
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	UStateObservationComponent* ObsComp = Owner->FindComponentByClass<UStateObservationComponent>();
	if (ObsComp)
	{
		SendObservation(ObsComp->GetObservationJson());
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: No StateObservationComponent found on owner"));
	}
}

void URLBridgeComponent::SendObservation(const FString& JsonPayload)
{
	if (!ClientSocket) return;

	const FString Message = JsonPayload + TEXT("\n");
	const FTCHARToUTF8 Converter(*Message);

	int32 BytesSent = 0;
	if (!ClientSocket->Send(reinterpret_cast<const uint8*>(Converter.Get()), Converter.Length(), BytesSent))
	{
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: Send failed, client may have disconnected"));
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
		ClientSocket = nullptr;
	}
}

void URLBridgeComponent::SendReward(float Reward, bool bDone)
{
	if (!ClientSocket) return;

	const FString Json = FString::Printf(TEXT("{\"reward\":%.4f,\"done\":%s}\n"),
		Reward, bDone ? TEXT("true") : TEXT("false"));

	const FTCHARToUTF8 Converter(*Json);
	int32 BytesSent = 0;
	if (!ClientSocket->Send(reinterpret_cast<const uint8*>(Converter.Get()), Converter.Length(), BytesSent))
	{
		UE_LOG(LogTemp, Warning, TEXT("RLBridge: Send failed, client may have disconnected"));
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
		ClientSocket = nullptr;
	}
}

void URLBridgeComponent::HandleGetProfileRequest()
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	UPlayerMemoryComponent* MemoryComp = Owner->FindComponentByClass<UPlayerMemoryComponent>();
	if (MemoryComp)
	{
		SendObservation(MemoryComp->GetDecayedProfileJson());
	}
	else
	{
		// No memory component — send neutral profile
		SendObservation(TEXT("{\"profile\":[0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5],\"total_encounters\":0,\"boss_wins\":0,\"win_rate\":0.0}"));
	}
}

void URLBridgeComponent::HandleSetPlayerId(const FString& PlayerId)
{
	CurrentPlayerId = PlayerId;
	UE_LOG(LogTemp, Log, TEXT("RLBridge: Player ID set to '%s'"), *PlayerId);

	// Load memory for this player
	AActor* Owner = GetOwner();
	if (!Owner) return;

	UPlayerMemoryComponent* MemoryComp = Owner->FindComponentByClass<UPlayerMemoryComponent>();
	if (MemoryComp)
	{
		MemoryComp->LoadMemory(PlayerId);
	}
}

void URLBridgeComponent::CleanupSockets()
{
	if (TcpListener)
	{
		TcpListener->Stop();
		delete TcpListener;
		TcpListener = nullptr;
	}

	{
		FScopeLock Lock(&PendingSocketMutex);
		if (PendingClientSocket)
		{
			ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(PendingClientSocket);
			PendingClientSocket = nullptr;
		}
	}

	if (ClientSocket)
	{
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
		ClientSocket = nullptr;
	}

	ReceiveBuffer.Empty();
	UE_LOG(LogTemp, Log, TEXT("RLBridge: Server stopped"));
}
