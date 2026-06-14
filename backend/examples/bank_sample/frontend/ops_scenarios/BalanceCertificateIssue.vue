<template>
  <section>
    <h1>잔액증명서 발급</h1>
    <label>계좌번호 <input v-model="form.accountNo" /></label>
    <label>기준일자 <input v-model="form.baseDate" /></label>
    <label>발급언어 <input v-model="form.language" /></label>
    <button type="button" @click="issueBalanceCertificate">증명서발급</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "CERT_910";
const screenName = "잔액증명서 발급";
const menuId = "MENU_BALANCE_CERTIFICATE";

const form = {
  accountNo: "",
  baseDate: "",
  language: "KO",
};

function issueBalanceCertificate() {
  if (!form.accountNo) {
    alert("계좌번호를 입력하세요.");
    return;
  }
  if (!form.baseDate) {
    alert("기준일자를 선택하세요.");
    return;
  }
  return axios.post("/api/ops/certificate/balance/issue", form);
}
</script>
