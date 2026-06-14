<template>
  <section>
    <h1>고액현금 인출 승인</h1>
    <label>계좌번호 <input v-model="form.accountNo" /></label>
    <label>인출금액 <input v-model.number="form.amount" /></label>
    <label>사전확인번호 <input v-model="form.preCheckNo" /></label>
    <button type="button" @click="approveCashWithdrawal">승인요청</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "CASH_610";
const screenName = "고액현금 인출 승인";
const menuId = "MENU_CASH_WITHDRAWAL_APPROVAL";

const form = {
  accountNo: "",
  amount: 0,
  preCheckNo: "",
};

function approveCashWithdrawal() {
  if (!form.accountNo) {
    alert("계좌번호를 입력하세요.");
    return;
  }
  if (!form.amount || form.amount < 10000000) {
    alert("고액현금 인출 대상 금액을 확인하세요.");
    return;
  }
  if (!form.preCheckNo) {
    alert("고액현금 사전확인을 완료하세요.");
    return;
  }
  return axios.post("/api/ops/cash/withdrawal/approve", form);
}
</script>
