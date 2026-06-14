<template>
  <section>
    <h1>자동이체 등록</h1>
    <label>출금계좌 <input v-model="form.withdrawAccountNo" /></label>
    <label>납부자번호 <input v-model="form.payerNo" /></label>
    <label>출금일 <input v-model.number="form.withdrawDay" /></label>
    <button type="button" @click="registerAutoDebit">등록</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "AUTO_710";
const screenName = "자동이체 등록";
const menuId = "MENU_AUTO_DEBIT_REGISTER";

const form = {
  withdrawAccountNo: "",
  payerNo: "",
  withdrawDay: 0,
};

function registerAutoDebit() {
  if (!form.withdrawAccountNo) {
    alert("출금계좌를 입력하세요.");
    return;
  }
  if (!form.payerNo || form.payerNo.length < 8) {
    alert("납부자번호 형식을 확인하세요.");
    return;
  }
  if (!form.withdrawDay || form.withdrawDay < 1 || form.withdrawDay > 28) {
    alert("출금일은 1일부터 28일 사이로 선택하세요.");
    return;
  }
  return axios.post("/api/ops/auto-debit/register", form);
}
</script>
