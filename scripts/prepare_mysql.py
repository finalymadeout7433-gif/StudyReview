"""V1 entry retired: prevents old ALL grants or reuse against the V2 main DB."""
if __name__ == '__main__':
    print('旧初始化入口已停用。请阅读 docs/01-Windows首次启动.md，使用新版人工确认流程。未连接数据库，未修改权限。')
    raise SystemExit(2)
