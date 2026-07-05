#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class UFirebaseAuthSubsystem;
class SEditableTextBox;
class STextBlock;

/**
 * M6 login screen — pure Slate, no UMG assets (the BossStatusHUD convention).
 * Full-viewport dark overlay with a centered panel: email + password boxes,
 * Sign In / Sign Up / PLAY AS GUEST, an error line, and the consent sentence
 * ("style data syncs to power your dossier" — NEXTSTEP Part 7 item 5).
 *
 * Owns ZERO auth state and makes ZERO requests: every button just forwards to
 * UFirebaseAuthSubsystem, which also owns showing/removing this widget and
 * pushes results back via SetErrorText / SetBusy. Colors lean on the HUD's
 * palette (UGameFeelSettings crimson accent) so the screen reads as the same
 * game, not a web form.
 */
class GAME_CORE_API SLoginScreen : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SLoginScreen) {}
		SLATE_ARGUMENT(TWeakObjectPtr<UFirebaseAuthSubsystem>, AuthSubsystem)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	/** Show a failure line under the inputs (auth subsystem pushes these). */
	void SetErrorText(const FText& InError);

	/** Disable the buttons while a request is in flight. */
	void SetBusy(bool bInBusy);

	/** Initial keyboard focus target for FInputModeUIOnly. */
	TSharedPtr<SWidget> GetInitialFocusWidget() const;

private:
	FReply OnSignInClicked();
	FReply OnSignUpClicked();
	FReply OnGuestClicked();

	/** Enter in the password box = Sign In. */
	void OnPasswordCommitted(const FText& Text, ETextCommit::Type CommitType);

	/** Shared validation: non-empty email/password, else set the error line locally. */
	bool ReadCredentials(FString& OutEmail, FString& OutPassword);

	TWeakObjectPtr<UFirebaseAuthSubsystem> Auth;
	TSharedPtr<SEditableTextBox> EmailBox;
	TSharedPtr<SEditableTextBox> PasswordBox;
	TSharedPtr<STextBlock> ErrorText;
	bool bBusy = false;
};
