#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Common/TcpListener.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "RLBridgeComponent.generated.h"

class UStateObservationComponent;
class UPlayerMemoryComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnRLActionReceived, int32, ActionIndex);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnRLResetRequested);

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API URLBridgeComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	URLBridgeComponent();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RLBridge")
	int32 ListenPort = 5555;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RLBridge", meta = (ClampMin = "1", ClampMax = "60"))
	int32 TickRate = 15;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "RLBridge")
	bool bAutoStart = true;

	// Fires when an action is received from the Python RL agent
	UPROPERTY(BlueprintAssignable, Category = "RLBridge")
	FOnRLActionReceived OnRLActionReceived;

	// Fires when the Python agent requests a reset
	UPROPERTY(BlueprintAssignable, Category = "RLBridge")
	FOnRLResetRequested OnRLResetRequested;

	UFUNCTION(BlueprintCallable, Category = "RLBridge")
	void StartServer();

	UFUNCTION(BlueprintCallable, Category = "RLBridge")
	void StopServer();

	UFUNCTION(BlueprintCallable, Category = "RLBridge")
	void SendObservation(const FString& JsonPayload);

	UFUNCTION(BlueprintCallable, Category = "RLBridge")
	void SendReward(float Reward, bool bDone);

	UFUNCTION(BlueprintPure, Category = "RLBridge")
	bool IsClientConnected() const { return ClientSocket != nullptr && ClientSocket->GetConnectionState() == SCS_Connected; }

	// Current player ID set by Python client
	UPROPERTY(BlueprintReadOnly, Category = "RLBridge")
	FString CurrentPlayerId;

private:
	FTcpListener* TcpListener = nullptr;
	FSocket* ClientSocket = nullptr;

	// Thread-safe handoff from listener thread to game thread
	FSocket* PendingClientSocket = nullptr;
	FCriticalSection PendingSocketMutex;

	FString ReceiveBuffer;
	float TickAccumulator = 0.0f;

	bool OnConnectionAccepted(FSocket* InSocket, const FIPv4Endpoint& Endpoint);
	void ProcessIncomingData();
	void ProcessMessage(const FString& Message);
	void HandleObserveRequest();
	void HandleGetProfileRequest();
	void HandleSetPlayerId(const FString& PlayerId);
	void HandleResetRequest();
	void CleanupSockets();
};
