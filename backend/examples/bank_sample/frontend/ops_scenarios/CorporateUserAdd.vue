<template>
  <section>
    <h1>기업뱅킹 사용자 등록</h1>
    <label>사업자번호 <input v-model="form.businessNo" /></label>
    <label>사용자ID <input v-model="form.userId" /></label>
    <label>OTP 일련번호 <input v-model="form.otpSerialNo" /></label>
    <button type="button" @click="addCorporateUser">사용자등록</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "CORP_810";
const screenName = "기업뱅킹 사용자 등록";
const menuId = "MENU_CORP_USER_ADD";

const form = {
  businessNo: "",
  userId: "",
  otpSerialNo: "",
};

function addCorporateUser() {
  if (!form.businessNo) {
    alert("사업자번호를 입력하세요.");
    return;
  }
  if (!form.userId) {
    alert("사용자ID를 입력하세요.");
    return;
  }
  if (!form.otpSerialNo) {
    alert("OTP 등록 정보를 확인하세요.");
    return;
  }
  return axios.post("/api/ops/corp/user/add", form);
}
</script>
