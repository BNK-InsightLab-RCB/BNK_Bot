package com.example.branch.ops;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ops")
public class BranchOpsScenarioController {
    private final BranchOpsScenarioService scenarioService;

    public BranchOpsScenarioController(BranchOpsScenarioService scenarioService) {
        this.scenarioService = scenarioService;
    }

    @PostMapping("/dormant/release")
    public void releaseDormant(@RequestBody DormantReleaseRequest request, User user) {
        scenarioService.releaseDormant(request, user);
    }

    @PostMapping("/limit/change")
    public void changeTransferLimit(@RequestBody TransferLimitRequest request, User user) {
        scenarioService.changeTransferLimit(request, user);
    }

    @PostMapping("/card/reissue")
    public void reissueCard(@RequestBody CardReissueRequest request, User user) {
        scenarioService.reissueCard(request, user);
    }

    @PostMapping("/loan/extend")
    public void extendLoan(@RequestBody LoanExtensionRequest request, User user) {
        scenarioService.extendLoan(request, user);
    }

    @PostMapping("/fund/redeem")
    public void redeemFund(@RequestBody FundRedemptionRequest request, User user) {
        scenarioService.redeemFund(request, user);
    }

    @PostMapping("/fx/remit")
    public void requestForeignRemittance(@RequestBody ForeignRemittanceRequest request, User user) {
        scenarioService.requestForeignRemittance(request, user);
    }

    @PostMapping("/cash/withdrawal/approve")
    public void approveCashWithdrawal(@RequestBody CashWithdrawalRequest request, User user) {
        scenarioService.approveCashWithdrawal(request, user);
    }

    @PostMapping("/auto-debit/register")
    public void registerAutoDebit(@RequestBody AutoDebitRequest request, User user) {
        scenarioService.registerAutoDebit(request, user);
    }

    @PostMapping("/corp/user/add")
    public void addCorporateUser(@RequestBody CorporateUserRequest request, User user) {
        scenarioService.addCorporateUser(request, user);
    }

    @PostMapping("/certificate/balance/issue")
    public void issueBalanceCertificate(@RequestBody BalanceCertificateRequest request, User user) {
        scenarioService.issueBalanceCertificate(request, user);
    }
}
