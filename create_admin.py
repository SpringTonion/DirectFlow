import getpass
import sys
from database_setup import create_master_database, get_connection
import auth_service

def main():
    # Đảm bảo CSDL đã tồn tại
    create_master_database()
    
    print("\n=== 👑 CẤP QUYỀN QUẢN TRỊ VIÊN (ADMIN) HỆ THỐNG ===")
    username = input("Nhập Username Admin: ").strip()
    email = input("Nhập Email (Enter để bỏ qua): ").strip() or None
    password = getpass.getpass("Nhập Mật khẩu (Không hiện ký tự): ")
    
    # Đăng ký tài khoản với role là 'admin'
    result = auth_service.register_user(username, password, email, role='admin')
    
    if result['success']:
        print(f"\n✅ THÀNH CÔNG: Đã khởi tạo Admin '{username}'!")
    elif 'đã tồn tại' in result['message']:
        print(f"\n⚠️ TÀI KHOẢN ĐÃ TỒN TẠI: {username}")
        choice = input("Bạn có muốn nâng cấp tài khoản này lên làm Admin không? (y/n): ").strip().lower()
        if choice == 'y':
            with get_connection() as conn:
                conn.execute("UPDATE users SET role = 'admin' WHERE username = ?", (username,))
                conn.commit()
            print("✅ Đã nâng cấp cấp bậc thành công!")
    else:
        print(f"\n❌ LỖI: {result['message']}")

if __name__ == '__main__':
    main()