<template>
  <section>
    <h1>대출 만기연장</h1>
    <label>대출계좌번호 <input v-model="form.loanNo" /></label>
    <label>연장개월 <input v-model.number="form.extendMonths" /></label>
    <label>
      약정서 동의
      <input v-model="form.contractAgreed" type="checkbox" />
    </label>
    <button type="button" @click="extendLoanMaturity">만기연장</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "LOAN_310";
const screenName = "대출 만기연장";
const menuId = "MENU_LOAN_EXTENSION";

const form = {
  loanNo: "",
  extendMonths: 0,
  contractAgreed: false,
};

function extendLoanMaturity() {
  if (!form.loanNo) {
    alert("대출계좌번호를 입력하세요.");
    return;
  }
  if (!form.extendMonths || form.extendMonths <= 0) {
    alert("연장개월을 확인하세요.");
    return;
  }
  if (!form.contractAgreed) {
    alert("약정서 동의가 필요합니다.");
    return;
  }
  return axios.post("/api/ops/loan/extend", form);
}
</script>
