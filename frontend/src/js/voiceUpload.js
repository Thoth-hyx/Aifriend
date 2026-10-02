export function voiceUploadError(file, duration = null) {
  if (!file) return '请选择音频文件'
  if (!/\.(wav|mp3|m4a)$/i.test(file.name)) return '仅支持 WAV（16bit）、MP3、M4A'
  if (!file.size || file.size > 10 * 1024 * 1024) return '音频文件不能为空，且不能超过 10 MB'
  if (Number.isFinite(duration) && (duration < 5 || duration > 60)) return '音频时长需为 5～60 秒，建议使用 10～20 秒清晰朗读'
  return ''
}
