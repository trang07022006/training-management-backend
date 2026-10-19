const ExcelJS = require('exceljs');
const path = require('path');

async function taoBaoCaoChuyenCan() {
    // 1. Dữ liệu lớp học
    const thongTinLop = {
        maLop: 'SCRUM-253',
        tenLop: 'Lập trình Web Fullstack'
    };

    // Danh sách 5 buổi học
    const danhSachBuoiHoc = [
        { id: 1, ngay: '01/10' },
        { id: 2, ngay: '03/10' },
        { id: 3, ngay: '05/10' },
        { id: 4, ngay: '08/10' },
        { id: 5, ngay: '10/10' }
    ];

    // Danh sách học viên và điểm danh ('P': Có mặt, 'V': Vắng)
    const danhSachHocVien = [
        { maHV: 'HV001', hoTen: 'Nguyễn Văn An', diemDanh: { 1: 'P', 2: 'P', 3: 'P', 4: 'P', 5: 'V' } },
        { maHV: 'HV002', hoTen: 'Trần Thị Mai', diemDanh: { 1: 'P', 2: 'V', 3: 'P', 4: 'P', 5: 'P' } },
        { maHV: 'HV003', hoTen: 'Lê Hoàng Nam', diemDanh: { 1: 'P', 2: 'P', 3: 'P', 4: 'P', 5: 'P' } },
        { maHV: 'HV004', hoTen: 'Phạm Quỳnh Anh', diemDanh: { 1: 'V', 2: 'V', 3: 'P', 4: 'P', 5: 'V' } }
    ];

    // 2. Khởi tạo file Excel
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet('Bảng Chuyên Cần');

    // Tiêu đề
    worksheet.mergeCells('A1:J1');
    const oTieuDe = worksheet.getCell('A1');
    oTieuDe.value = `BÁO CÁO CHUYÊN CẦN - LỚP: ${thongTinLop.maLop} (${thongTinLop.tenLop.toUpperCase()})`;
    oTieuDe.font = { name: 'Arial', size: 15, bold: true, color: { argb: '1F4E79' } };
    oTieuDe.alignment = { vertical: 'middle', horizontal: 'center' };
    worksheet.getRow(1).height = 32;

    worksheet.addRow([]); // Dòng trống cách dòng

    // 3. Header bảng
    const headers = ['STT', 'Mã HV', 'Họ và tên'];
    danhSachBuoiHoc.forEach((buoi, idx) => {
        headers.push(`B${idx + 1} (${buoi.ngay})`);
    });
    headers.push('Tổng đi học', 'Tổng vắng', 'Tỷ lệ đi học');

    const hangHeader = worksheet.addRow(headers);
    hangHeader.height = 26;
    hangHeader.eachCell((cell) => {
        cell.font = { name: 'Arial', bold: true, color: { argb: 'FFFFFF' } };
        cell.fill = {
            type: 'pattern',
            pattern: 'solid',
            fgColor: { argb: '2F5597' }
        };
        cell.alignment = { vertical: 'middle', horizontal: 'center' };
        cell.border = {
            top: { style: 'thin' },
            left: { style: 'thin' },
            bottom: { style: 'thin' },
            right: { style: 'thin' }
        };
    });

    // 4. Đổ dữ liệu học viên
    danhSachHocVien.forEach((hv, idx) => {
        const dongHocVien = [idx + 1, hv.maHV, hv.hoTen];
        let soBuoiDiHoc = 0;
        let soBuoiVang = 0;

        danhSachBuoiHoc.forEach((buoi) => {
            const trangThai = hv.diemDanh[buoi.id] || '-';
            dongHocVien.push(trangThai);
            if (trangThai === 'P') soBuoiDiHoc++;
            else if (trangThai === 'V') soBuoiVang++;
        });

        const tyLe = ((soBuoiDiHoc / danhSachBuoiHoc.length) * 100).toFixed(1) + '%';
        dongHocVien.push(soBuoiDiHoc, soBuoiVang, tyLe);

        const hangMoi = worksheet.addRow(dongHocVien);
        hangMoi.height = 22;

        hangMoi.eachCell((cell, colNumber) => {
            cell.font = { name: 'Arial', size: 11 };
            cell.border = {
                top: { style: 'thin' },
                left: { style: 'thin' },
                bottom: { style: 'thin' },
                right: { style: 'thin' }
            };
            if (colNumber === 3) {
                cell.alignment = { vertical: 'middle', horizontal: 'left' };
            } else {
                cell.alignment = { vertical: 'middle', horizontal: 'center' };
            }
            if (cell.value === 'V') {
                cell.font = { name: 'Arial', bold: true, color: { argb: 'C00000' } };
            }
        });
    });

    // 5. Chỉnh độ rộng cột tự động
    worksheet.columns.forEach((column) => {
        let maxLen = 0;
        column.eachCell({ includeEmpty: true }, (cell) => {
            const cellLength = cell.value ? cell.value.toString().length : 0;
            if (cellLength > maxLen) maxLen = cellLength;
        });
        column.width = Math.max(maxLen + 4, 12);
    });

    // 6. Đặt tên tệp theo Yêu cầu (Mã lớp + Ngày xuất)
    const now = new Date();
    const nam = now.getFullYear();
    const thang = String(now.getMonth() + 1).padStart(2, '0');
    const ngay = String(now.getDate()).padStart(2, '0');
    const chuoiNgay = `${nam}${thang}${ngay}`;

    const tenTep = `BaoCao_ChuyenCan_${thongTinLop.maLop}_${chuoiNgay}.xlsx`;
    const duongDanFile = path.join(__dirname, tenTep);

    await workbook.xlsx.writeFile(duongDanFile);

    console.log(`\n=== XUAT FILE THANH CONG! ===`);
    console.log(`Ten file: ${tenTep}`);
    console.log(`Duong dan: ${duongDanFile}\n`);
}

taoBaoCaoChuyenCan().catch(err => console.error("Loi:", err));