#include "LoginScreen.h"

#include "FirebaseAuthSubsystem.h"
#include "GameFeelSettings.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

namespace LoginScreenStyle
{
	// Dark palette matched to the boss HUD's backplate blacks; the accent is the
	// HUD's crimson so the login reads as part of the game.
	static const FLinearColor Scrim(0.0f, 0.0f, 0.0f, 0.85f);
	static const FLinearColor Panel(0.045f, 0.055f, 0.07f, 0.98f);
	static const FLinearColor PanelBorder(0.12f, 0.13f, 0.16f, 1.0f);
	static const FLinearColor TextMain(0.78f, 0.80f, 0.83f, 1.0f);
	static const FLinearColor TextDim(0.45f, 0.47f, 0.51f, 1.0f);
	static const FLinearColor ErrorRed(1.0f, 0.35f, 0.29f, 1.0f);
	static const FLinearColor InputBack(0.09f, 0.10f, 0.12f, 1.0f);
}

void SLoginScreen::Construct(const FArguments& InArgs)
{
	Auth = InArgs._AuthSubsystem;

	// Crimson accent from the shared feel settings (falls back to its C++ default
	// if the ini was never touched — always a sane color).
	const FLinearColor Accent = GetDefault<UGameFeelSettings>()->BossBarHealthColor;

	const FSlateFontInfo TitleFont = FCoreStyle::GetDefaultFontStyle("Bold", 26);
	const FSlateFontInfo LabelFont = FCoreStyle::GetDefaultFontStyle("Regular", 12);
	const FSlateFontInfo InputFont = FCoreStyle::GetDefaultFontStyle("Regular", 14);
	const FSlateFontInfo ButtonFont = FCoreStyle::GetDefaultFontStyle("Bold", 14);
	const FSlateFontInfo SmallFont = FCoreStyle::GetDefaultFontStyle("Regular", 10);

	const TAttribute<bool> ButtonsEnabled = TAttribute<bool>::CreateLambda([this]() { return !bBusy; });

	ChildSlot
	[
		// Full-screen scrim.
		SNew(SBorder)
		.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
		.BorderBackgroundColor(LoginScreenStyle::Scrim)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		.Padding(0.0f)
		[
			SNew(SBox)
			.WidthOverride(440.0f)
			[
				SNew(SBorder)
				.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
				.BorderBackgroundColor(LoginScreenStyle::Panel)
				.Padding(FMargin(36.0f, 32.0f))
				[
					SNew(SVerticalBox)

					// Title + accent underline.
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(STextBlock)
						.Text(NSLOCTEXT("LoginScreen", "Title", "GAME_CORE"))
						.Font(TitleFont)
						.ColorAndOpacity(LoginScreenStyle::TextMain)
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.0f, 6.0f, 0.0f, 4.0f)
					[
						SNew(SBox).WidthOverride(64.0f).HeightOverride(3.0f)
						[
							SNew(SBorder)
							.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
							.BorderBackgroundColor(Accent)
						]
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.0f, 0.0f, 0.0f, 22.0f)
					[
						SNew(STextBlock)
						.Text(NSLOCTEXT("LoginScreen", "Subtitle", "SUBJECT DOSSIER ACCESS"))
						.Font(LabelFont)
						.ColorAndOpacity(LoginScreenStyle::TextDim)
					]

					// Email.
					+ SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 10.0f)
					[
						SAssignNew(EmailBox, SEditableTextBox)
						.Font(InputFont)
						.HintText(NSLOCTEXT("LoginScreen", "EmailHint", "email"))
						.BackgroundColor(LoginScreenStyle::InputBack)
						.ForegroundColor(LoginScreenStyle::TextMain)
					]

					// Password.
					+ SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 8.0f)
					[
						SAssignNew(PasswordBox, SEditableTextBox)
						.Font(InputFont)
						.HintText(NSLOCTEXT("LoginScreen", "PasswordHint", "password"))
						.IsPassword(true)
						.BackgroundColor(LoginScreenStyle::InputBack)
						.ForegroundColor(LoginScreenStyle::TextMain)
						.OnTextCommitted(this, &SLoginScreen::OnPasswordCommitted)
					]

					// Error line (empty until something fails).
					+ SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 14.0f)
					[
						SAssignNew(ErrorText, STextBlock)
						.Text(FText::GetEmpty())
						.Font(LabelFont)
						.ColorAndOpacity(LoginScreenStyle::ErrorRed)
						.AutoWrapText(true)
					]

					// Sign In / Sign Up row.
					+ SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 10.0f)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().FillWidth(1.0f).Padding(0.0f, 0.0f, 5.0f, 0.0f)
						[
							SNew(SButton)
							.HAlign(HAlign_Center)
							.ContentPadding(FMargin(0.0f, 10.0f))
							.IsEnabled(ButtonsEnabled)
							.OnClicked(this, &SLoginScreen::OnSignInClicked)
							[
								SNew(STextBlock)
								.Text(NSLOCTEXT("LoginScreen", "SignIn", "SIGN IN"))
								.Font(ButtonFont)
							]
						]
						+ SHorizontalBox::Slot().FillWidth(1.0f).Padding(5.0f, 0.0f, 0.0f, 0.0f)
						[
							SNew(SButton)
							.HAlign(HAlign_Center)
							.ContentPadding(FMargin(0.0f, 10.0f))
							.IsEnabled(ButtonsEnabled)
							.OnClicked(this, &SLoginScreen::OnSignUpClicked)
							[
								SNew(STextBlock)
								.Text(NSLOCTEXT("LoginScreen", "SignUp", "SIGN UP"))
								.Font(ButtonFont)
							]
						]
					]

					// Guest path — always available, never blocked by network.
					+ SVerticalBox::Slot().AutoHeight().Padding(0.0f, 0.0f, 0.0f, 18.0f)
					[
						SNew(SButton)
						.HAlign(HAlign_Center)
						.ContentPadding(FMargin(0.0f, 10.0f))
						.IsEnabled(ButtonsEnabled)
						.OnClicked(this, &SLoginScreen::OnGuestClicked)
						[
							SNew(STextBlock)
							.Text(NSLOCTEXT("LoginScreen", "Guest", "PLAY AS GUEST"))
							.Font(ButtonFont)
						]
					]

					// Consent line (NEXTSTEP Part 7 item 5).
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(STextBlock)
						.Text(NSLOCTEXT("LoginScreen", "Consent",
							"Signing in syncs your combat style data to power your online dossier."))
						.Font(SmallFont)
						.ColorAndOpacity(LoginScreenStyle::TextDim)
						.AutoWrapText(true)
						.Justification(ETextJustify::Center)
					]
				]
			]
		]
	];
}

void SLoginScreen::SetErrorText(const FText& InError)
{
	if (ErrorText.IsValid())
	{
		ErrorText->SetText(InError);
	}
}

void SLoginScreen::SetBusy(bool bInBusy)
{
	bBusy = bInBusy;
}

TSharedPtr<SWidget> SLoginScreen::GetInitialFocusWidget() const
{
	return EmailBox;
}

bool SLoginScreen::ReadCredentials(FString& OutEmail, FString& OutPassword)
{
	OutEmail = EmailBox.IsValid() ? EmailBox->GetText().ToString().TrimStartAndEnd() : FString();
	OutPassword = PasswordBox.IsValid() ? PasswordBox->GetText().ToString() : FString();

	if (OutEmail.IsEmpty() || OutPassword.IsEmpty())
	{
		SetErrorText(NSLOCTEXT("LoginScreen", "MissingFields", "Enter an email and a password."));
		return false;
	}
	return true;
}

FReply SLoginScreen::OnSignInClicked()
{
	FString Email, Password;
	if (ReadCredentials(Email, Password) && Auth.IsValid())
	{
		SetErrorText(FText::GetEmpty());
		Auth->SignIn(Email, Password);
	}
	return FReply::Handled();
}

FReply SLoginScreen::OnSignUpClicked()
{
	FString Email, Password;
	if (ReadCredentials(Email, Password) && Auth.IsValid())
	{
		SetErrorText(FText::GetEmpty());
		Auth->SignUp(Email, Password);
	}
	return FReply::Handled();
}

FReply SLoginScreen::OnGuestClicked()
{
	if (Auth.IsValid())
	{
		Auth->ContinueAsGuest();
	}
	return FReply::Handled();
}

void SLoginScreen::OnPasswordCommitted(const FText& /*Text*/, ETextCommit::Type CommitType)
{
	if (CommitType == ETextCommit::OnEnter && !bBusy)
	{
		OnSignInClicked();
	}
}
